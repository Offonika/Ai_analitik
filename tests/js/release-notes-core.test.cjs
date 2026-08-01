const test = require("node:test");
const assert = require("node:assert/strict");

const core = require("../../src/wb_unit_economics/web/static/release-notes-core.js");

test("orders semantic versions newest first", () => {
  const releases = core.normalizeReleaseList([
    { version: "v2.63" },
    { version: "v2.64-rc.1" },
    { version: "v2.64" },
  ]);
  assert.deepEqual(releases.map((item) => item.version), [
    "v2.64",
    "v2.64-rc.1",
    "v2.63",
  ]);
});

test("first visit reports only the latest release as unread", () => {
  assert.deepEqual(
    core.unreadVersions(
      [{ version: "v2.64" }, { version: "v2.63" }, { version: "v2.62" }],
      "",
    ),
    ["v2.64"],
  );
});

test("known last seen version reports every newer release", () => {
  assert.deepEqual(
    core.unreadVersions(
      [{ version: "v2.65" }, { version: "v2.64" }, { version: "v2.63" }],
      "v2.63",
    ),
    ["v2.65", "v2.64"],
  );
});

test("storage failures are fail-soft", () => {
  const storage = {
    getItem() {
      throw new Error("disabled");
    },
    setItem() {
      throw new Error("disabled");
    },
  };
  assert.equal(core.readLastSeen(storage, "key"), "");
  assert.equal(core.writeLastSeen(storage, "key", "v2.64"), false);
});

test("parses release and guide deep links", () => {
  assert.deepEqual(core.parseReleaseRoute("#news/v2.64"), {
    workspace: "news",
    version: "v2.64",
    guideId: "",
    valid: true,
  });
  assert.deepEqual(core.parseReleaseRoute("#guide/download-excel"), {
    workspace: "guide",
    version: "",
    guideId: "download-excel",
    valid: true,
  });
  assert.equal(core.parseReleaseRoute("#news/invalid"), null);
});

test("filters guide entries by all query terms", () => {
  const entries = [
    {
      id: "download-excel",
      title: "Скачать Excel",
      description: "Текущий опубликованный отчёт",
    },
    {
      id: "refresh-status",
      title: "Обновить статус",
      description: "Последний запуск",
    },
  ];
  assert.deepEqual(
    core.filterGuideEntries(entries, "excel отчёт").map((item) => item.id),
    ["download-excel"],
  );
  assert.equal(core.filterGuideEntries(entries, "не найдено").length, 0);
});
