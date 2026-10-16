const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

// Exercise the shipped TypeScript without introducing a separate test dependency.
function harness(fetch, globals = {}) {
  const cache = new Map();
  const context = vm.createContext({
    fetch, Headers, Response, FormData, AbortController, URLSearchParams, setTimeout, clearTimeout,
    ...globals,
  });
  function load(name) {
    const filename = path.resolve(__dirname, "..", "src", `${name}.ts`);
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { exports: {} };
    cache.set(filename, module);
    const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    const run = vm.runInContext(`(function(require, module, exports) { ${source}\n})`, context);
    run((relative) => load(relative.replace(/^\.\//, "")), module, module.exports);
    return module.exports;
  }
  return { auth: load("auth"), api: load("services").default };
}

const grant = { tenant_id: "tenant-a", collection_id: "project-a" };
const otherGrant = { tenant_id: "tenant-a", collection_id: "project-b" };
const session = (roles = ["read", "ingest", "admin"]) => ({
  user_id: "individual-user", roles, scopes: [grant, otherGrant],
});
const json = (data, status = 200) => new Response(JSON.stringify(data), { status });
const file = () => Object.assign(new Blob(["document"]), { name: "document.txt" });

test("retention is opt-in and saved answers use authenticated current-scope requests", async () => {
  const calls = [];
  const { auth, api } = harness(async (url, init) => {
    calls.push({ url, init });
    return json(url.endsWith("/session") ? session() : { answer: "answer", answer_id: "saved" });
  });
  await auth.loginUser("individual-key", "http://api");
  await api.askQuestion("Save?", "source", undefined, undefined, undefined, {}, true);
  assert.equal(JSON.parse(calls.at(-1).init.body).retain_answer, true);
  await api.listSavedAnswers();
  assert.match(calls.at(-1).url, /answers\?tenant_id=tenant-a&collection_id=project-a$/);
  await api.readSavedAnswer("saved/id");
  assert.match(calls.at(-1).url, /answers\/saved%2Fid$/);
  await api.deleteSavedAnswer("saved");
  assert.equal(calls.at(-1).init.method, "DELETE");
});

test("capacity errors give a safe retry message without exposing server details", async () => {
  const { auth, api } = harness(async (url) => {
    if (url.endsWith("/session")) return json(session());
    return json({ detail: "operator-only internal details" }, 503);
  });
  await auth.loginUser("example-individual-key", "http://api");
  await assert.rejects(api.askQuestion("What?", "document"), (error) => {
    assert.match(error.message, /busy.*retry shortly/i);
    assert.doesNotMatch(error.message, /operator-only|permissions/i);
    return true;
  });
  assert.equal(auth.getCurrentUser().user_id, "individual-user");
});

test("sign-in uses the real session and requests attach the in-memory key and exact grant", async () => {
  const calls = [];
  const { auth, api } = harness(async (url, init) => {
    calls.push({ url, init });
    return json(url.endsWith("/session") ? session() : { answer: "Grounded answer" });
  });
  await auth.loginUser("example-individual-key", "http://api");
  assert.equal(auth.getCurrentUser().user_id, "individual-user");
  assert.equal(auth.getCurrentScope().collection_id, grant.collection_id);
  const answer = await api.askQuestion("What?", "document");
  assert.equal(answer.answer, "Grounded answer");
  assert.equal(calls[0].init.headers.Authorization, "Bearer example-individual-key");
  assert.equal(calls[1].init.headers.get("Authorization"), "Bearer example-individual-key");
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    ...grant, question: "What?", document_id: "document",
  });
  await assert.rejects(api.askQuestion("What?", "document", "ungranted"), /authorized/);
  auth.selectScope(otherGrant);
  await api.askQuestion("What?", "document");
  assert.equal(JSON.parse(calls[2].init.body).collection_id, "project-b");
});

test("read-only users cannot ingest", async () => {
  let requests = 0;
  const { auth, api } = harness(async () => { requests++; return json(session(["read"])); });
  await auth.loginUser("read-key", "http://api");
  await assert.rejects(api.uploadDocument(file(), "document"), /ingest role/);
  await assert.rejects(api.uploadSharePoint("https://example.test/file", "document"), /ingest role/);
  assert.equal(requests, 1);
  auth.logoutUser();
  assert.equal(auth.getCurrentUser(), null);
  await assert.rejects(api.askQuestion("What?", "document"));
});

test("every role combination is explicit, including admin without read or ingest", { timeout: 3000 }, async () => {
  for (const roles of [
    [], ["read"], ["ingest"], ["admin"], ["read", "ingest"],
    ["read", "admin"], ["ingest", "admin"], ["read", "ingest", "admin"],
  ]) {
    const calls = [];
    const { auth, api } = harness(async (url) => {
      calls.push(url);
      if (url.endsWith("/session")) return json(session(roles));
      return json(url.endsWith("/ask") ? { answer: "Grounded answer" } : { status: "success" });
    });
    await auth.loginUser("example-key", "http://api");
    for (const [permitted, request, endpoint] of [
      [roles.includes("read"), () => api.askQuestion("What?", "document"), "/ask"],
      [roles.includes("ingest"), () => api.uploadDocument(file(), "document"), "/upload"],
      [roles.includes("ingest") && roles.includes("admin"),
        () => api.uploadSharePoint("https://example.test/file", "document"), "/upload-sharepoint"],
    ]) {
      const before = calls.length;
      if (permitted) {
        await request();
        assert.equal(calls.length, before + 1);
        assert.ok(calls.at(-1).endsWith(endpoint));
      } else {
        await assert.rejects(request(), /requires the .* role/);
        assert.equal(calls.length, before);
      }
    }
    await api.checkHealth();
    assert.ok(calls.at(-1).endsWith("/session"));
    assert.ok(calls.every((url) => !url.endsWith("/metrics")));
  }
});

test("queued ingestion waits for completion and authenticates the job poll", async () => {
  let resolvePoll;
  let pollStarted;
  const started = new Promise((resolve) => { pollStarted = resolve; });
  const { auth, api } = harness(async (url, init) => {
    if (url.endsWith("/session")) return json(session());
    if (url.endsWith("/upload")) {
      assert.equal(init.headers.get("Authorization"), "Bearer ingest-key");
      assert.equal(init.body.get("tenant_id"), grant.tenant_id);
      assert.equal(init.body.get("collection_id"), grant.collection_id);
      assert.equal(init.body.get("document_id"), "document");
      return json({ job_id: "job-1", status: "queued" });
    }
    assert.ok(url.endsWith("/ingestion-jobs/job-1"));
    assert.equal(init.headers.get("Authorization"), "Bearer ingest-key");
    pollStarted();
    return new Promise((resolve) => { resolvePoll = resolve; });
  });
  await auth.loginUser("ingest-key", "http://api");
  let finished = false;
  const upload = api.uploadDocument(file(), "document").then((result) => { finished = true; return result; });
  await started;
  assert.equal(finished, false);
  resolvePoll(json({ status: "completed", result: { status: "success", chunks: 3 } }));
  assert.equal((await upload).chunks, 3);
});

test("failed jobs produce a clear error without exposing server details", async () => {
  const { auth, api } = harness(async (url) => {
    if (url.endsWith("/session")) return json(session());
    return json(url.endsWith("/upload")
      ? { job_id: "job-1", status: "queued" }
      : { status: "failed", error: "operator-only details" });
  });
  await auth.loginUser("ingest-key", "http://api");
  await assert.rejects(api.uploadDocument(file(), "document"), (error) =>
    /processing failed/i.test(error.message) && !error.message.includes("operator-only"));
});

test("visual processing is explicit and preserves the generated description", async () => {
  const { auth, api } = harness(async (url, init) => {
    if (url.endsWith("/session")) return json(session());
    assert.equal(init.body.get("image_mode"), "describe");
    return json({ content_kind: "ai_image_description", image_description: "A red rectangle.", chunks: 1 });
  });
  await auth.loginUser("ingest-key", "http://api");
  const result = await api.uploadDocument(file(), "image", undefined, undefined, undefined, {}, "describe");
  assert.equal(result.image_description, "A red rectangle.");
});

for (const queued of [false, true]) {
  test(`safe image error codes are explained without reflecting bodies (queued=${queued})`, async () => {
    const { auth, api } = harness(async (url) => {
      if (url.endsWith("/session")) return json(session());
      if (queued && url.endsWith("/upload")) return json({ job_id: "ocr-job", status: "queued" });
      return json({
        status: "failed", error_code: "ocr_unavailable",
        error: "private-error-details", detail: "private-error-details",
      }, queued ? 200 : 503);
    });
    await auth.loginUser("ingest-key", "http://api");
    await assert.rejects(api.uploadDocument(file(), "image"), (error) =>
      /choose AI visual description/i.test(error.message) && !error.message.includes("private-error-details"));
  });
}

test("401 clears the current session and notifies the UI", async () => {
  const { auth, api } = harness(async (url) =>
    url.endsWith("/session") ? json(session()) : json({}, 401));
  await auth.loginUser("example-key", "http://api");
  let notification;
  auth.subscribeSession((message) => { notification = message; });
  await assert.rejects(api.askQuestion("What?", "document"), /expired/);
  assert.equal(auth.getCurrentUser(), null);
  assert.equal(auth.getCurrentScope(), null);
  assert.match(notification, /sign in again/i);
});

test("a late 401 from an older key cannot expire a replacement identity", { timeout: 2000 }, async () => {
  let resolveAsk;
  let signIns = 0;
  const { auth, api } = harness(async (url) => {
    if (url.endsWith("/session")) return json({
      ...session(), user_id: ++signIns === 1 ? "old-user" : "replacement-user",
    });
    return new Promise((resolve) => { resolveAsk = resolve; });
  });
  await auth.loginUser("old-key", "http://api");
  const pending = api.askQuestion("What?", "document");
  const rejected = assert.rejects(pending, /cancelled/);
  await auth.loginUser("new-key", "http://api");
  resolveAsk(json({}, 401));
  await rejected;
  assert.equal(auth.getCurrentUser().user_id, "replacement-user");
});

test("late successful answers are discarded after identity or scope changes, including delayed bodies", { timeout: 3000 }, async () => {
  for (const change of ["identity", "scope"]) {
    for (const phase of ["headers", "body"]) {
      let resolveResponse;
      let requestStarted;
      let signIns = 0;
      const started = new Promise((resolve) => { requestStarted = resolve; });
      const late = new Promise((resolve) => { resolveResponse = resolve; });
      const { auth, api } = harness(async (url) => {
        if (url.endsWith("/session")) return json({
          ...session(), user_id: ++signIns === 1 ? "old-user" : "replacement-user",
        });
        if (phase === "headers") {
          requestStarted();
          return late;
        }
        const response = json({ answer: "Old private answer" });
        response.blob = () => { requestStarted(); return late; };
        return response;
      });
      await auth.loginUser("old-key", "http://api");
      const rejected = assert.rejects(api.askQuestion("What?", "document"), /cancelled/);
      await started;
      if (change === "identity") await auth.loginUser("new-key", "http://api");
      else auth.selectScope(otherGrant);
      const version = auth.getSessionGeneration();
      resolveResponse(phase === "headers"
        ? json({ answer: "Old private answer" })
        : new Blob([JSON.stringify({ answer: "Old private answer" })]));
      await rejected;
      assert.equal(auth.getSessionGeneration(), version);
      assert.equal(auth.getCurrentUser().user_id, change === "identity" ? "replacement-user" : "old-user");
      assert.equal(auth.getCurrentScope().collection_id, change === "scope" ? "project-b" : "project-a");
    }
  }
});

test("late queued uploads cannot start polling under a replacement identity or scope", { timeout: 3000 }, async () => {
  for (const change of ["identity", "scope"]) {
    let resolveUpload;
    let uploadStarted;
    let polls = 0;
    const started = new Promise((resolve) => { uploadStarted = resolve; });
    const { auth, api } = harness(async (url) => {
      if (url.endsWith("/session")) return json(session());
      if (url.endsWith("/upload")) {
        uploadStarted();
        return new Promise((resolve) => { resolveUpload = resolve; });
      }
      polls++;
      return json({ status: "completed" });
    });
    await auth.loginUser("old-key", "http://api");
    const rejected = assert.rejects(api.uploadDocument(file(), "document"), /cancelled/);
    await started;
    if (change === "identity") await auth.loginUser("new-key", "http://api");
    else auth.selectScope(otherGrant);
    resolveUpload(json({ status: "queued", job_id: "old-job" }));
    await rejected;
    assert.equal(polls, 0);
  }
});

test("late completed polls cannot return old document state to a replacement identity", { timeout: 2000 }, async () => {
  let resolvePoll;
  let pollStarted;
  const started = new Promise((resolve) => { pollStarted = resolve; });
  const { auth, api } = harness(async (url) => {
    if (url.endsWith("/session")) return json(session());
    if (url.endsWith("/upload")) return json({ status: "queued", job_id: "old-job" });
    pollStarted();
    return new Promise((resolve) => { resolvePoll = resolve; });
  });
  await auth.loginUser("old-key", "http://api");
  const rejected = assert.rejects(api.uploadDocument(file(), "document"), /cancelled/);
  await started;
  await auth.loginUser("new-key", "http://api");
  resolvePoll(json({ status: "completed", result: { status: "success", document_id: "old-document" } }));
  await rejected;
  assert.ok(auth.getCurrentUser());
});

test("changing scope aborts pending work and discards a late ingestion completion", async () => {
  let resolvePoll;
  let pollStarted;
  let oldSignal;
  const started = new Promise((resolve) => { pollStarted = resolve; });
  const { auth, api } = harness(async (url, init) => {
    if (url.endsWith("/session")) return json(session());
    if (url.endsWith("/upload")) return json({ status: "queued", job_id: "job-1" });
    oldSignal = init.signal;
    pollStarted();
    return new Promise((resolve) => { resolvePoll = resolve; });
  });
  await auth.loginUser("example-key", "http://api");
  const pending = api.uploadDocument(file(), "document");
  const rejected = assert.rejects(pending, /cancelled/);
  await started;
  auth.selectScope(otherGrant);
  assert.equal(oldSignal.aborted, true);
  resolvePoll(json({ status: "completed" }));
  await rejected;
});

test("polling stops at its five-minute deadline with a clear timeout", async () => {
  let now = 0;
  let polls = 0;
  const { auth, api } = harness(async (url) => {
    if (url.endsWith("/session")) return json(session());
    if (url.endsWith("/upload")) return json({ status: "queued", job_id: "job-1" });
    polls++;
    now = 300001;
    return json({ status: "running" });
  }, { Date: { now: () => now } });
  await auth.loginUser("example-key", "http://api");
  await assert.rejects(api.uploadDocument(file(), "document"), /timed out after five minutes/);
  assert.equal(polls, 1);
});

test("cancelling a job poll aborts the request and returns no ready result", async () => {
  let pollStarted;
  const started = new Promise((resolve) => { pollStarted = resolve; });
  const { auth, api } = harness(async (url, init) => {
    if (url.endsWith("/session")) return json(session());
    if (url.endsWith("/upload")) return json({ status: "queued", job_id: "job-1" });
    pollStarted();
    return new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
  });
  await auth.loginUser("example-key", "http://api");
  const controller = new AbortController();
  const rejected = assert.rejects(
    api.uploadDocument(file(), "document", undefined, undefined, controller.signal),
    /cancelled/
  );
  await started;
  controller.abort();
  await rejected;
});

test("a key with no server grants cannot establish a session", async () => {
  const { auth } = harness(async () => json({ ...session(), scopes: [] }));
  await assert.rejects(auth.loginUser("ungranted-key", "http://api"), /No valid/);
  assert.equal(auth.getCurrentUser(), null);
  assert.equal(auth.getCurrentScope(), null);
});
