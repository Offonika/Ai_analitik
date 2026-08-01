(function exposeReleaseNotesCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ReleaseNotesCore = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function buildReleaseNotesCore() {
  "use strict";

  function normalizeVersion(value) {
    return String(value || "").trim().replace(/^v/i, "");
  }

  function versionParts(value) {
    const normalized = normalizeVersion(value);
    const match = normalized.match(
      /^(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$/,
    );
    if (!match) {
      return null;
    }
    return {
      major: Number(match[1]),
      minor: Number(match[2]),
      patch: Number(match[3] || 0),
      prerelease: match[4] || "",
    };
  }

  function compareVersions(left, right) {
    const leftParts = versionParts(left);
    const rightParts = versionParts(right);
    if (!leftParts || !rightParts) {
      return normalizeVersion(left).localeCompare(normalizeVersion(right), "en", {
        numeric: true,
      });
    }
    for (const key of ["major", "minor", "patch"]) {
      if (leftParts[key] !== rightParts[key]) {
        return leftParts[key] - rightParts[key];
      }
    }
    if (leftParts.prerelease === rightParts.prerelease) {
      return 0;
    }
    if (!leftParts.prerelease) {
      return 1;
    }
    if (!rightParts.prerelease) {
      return -1;
    }
    return leftParts.prerelease.localeCompare(rightParts.prerelease, "en", {
      numeric: true,
    });
  }

  function normalizeReleaseList(releases) {
    return Array.isArray(releases)
      ? [...releases].sort((left, right) => compareVersions(right.version, left.version))
      : [];
  }

  function unreadVersions(releases, lastSeenVersion) {
    const ordered = normalizeReleaseList(releases);
    if (!ordered.length) {
      return [];
    }
    const seen = normalizeVersion(lastSeenVersion);
    if (!seen) {
      return [ordered[0].version];
    }
    const seenIndex = ordered.findIndex(
      (release) => normalizeVersion(release.version) === seen,
    );
    if (seenIndex < 0) {
      return [ordered[0].version];
    }
    return ordered.slice(0, seenIndex).map((release) => release.version);
  }

  function readLastSeen(storage, key) {
    try {
      return String(storage?.getItem(key) || "").trim();
    } catch (_error) {
      return "";
    }
  }

  function writeLastSeen(storage, key, version) {
    try {
      storage?.setItem(key, String(version || ""));
      return true;
    } catch (_error) {
      return false;
    }
  }

  function parseReleaseRoute(hash) {
    const value = String(hash || "").replace(/^#/, "").replace(/\/+$/, "");
    if (value === "news") {
      return { workspace: "news", version: "", guideId: "", valid: true };
    }
    const news = value.match(
      /^news\/(v\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?)$/,
    );
    if (news) {
      return { workspace: "news", version: news[1], guideId: "", valid: true };
    }
    const guide = value.match(/^guide\/([a-z0-9]+(?:-[a-z0-9]+)*)$/);
    if (guide) {
      return { workspace: "guide", version: "", guideId: guide[1], valid: true };
    }
    return null;
  }

  function guideSearchText(entry) {
    return [entry.title, entry.description, entry.result, entry.caution, entry.troubleshooting]
      .map((value) => String(value || "").toLocaleLowerCase("ru"))
      .join(" ");
  }

  function filterGuideEntries(entries, query) {
    const normalized = String(query || "").trim().toLocaleLowerCase("ru");
    if (!normalized) {
      return Array.isArray(entries) ? [...entries] : [];
    }
    const terms = normalized.split(/\s+/).filter(Boolean);
    return (Array.isArray(entries) ? entries : []).filter((entry) => {
      const searchable = guideSearchText(entry);
      return terms.every((term) => searchable.includes(term));
    });
  }

  return {
    compareVersions,
    filterGuideEntries,
    normalizeReleaseList,
    normalizeVersion,
    parseReleaseRoute,
    readLastSeen,
    unreadVersions,
    versionParts,
    writeLastSeen,
  };
});
