#!/usr/bin/env python3
"""
Stage 6 Acceptance Criteria Verification Script

Verifies the "Сборки" (modpack catalog) section:
1. Provider swiper switches between Modrinth / CurseForge / GitHub screens
2. Modrinth catalog loads tags and a first page of results
3. Game-version / category / loader filters and sorting reach the API
4. Search text is debounced and reaches the API
5. "Показать ещё" appends the next page
6. Opening a card shows the detail screen and loads its versions
7. "Назад" returns to the catalog
8. Core helpers (facets, monogram, download formatting) behave correctly
9. shutdown() stops the background threads

No real network access: a stub catalog client is injected.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent / "src"))

from PyQt6.QtWidgets import QApplication

from core.modrinth_catalog import (
    ModrinthCatalogClient, ModpackTags, ModpackHit, ModpackDetail,
    ModpackVersionInfo, SearchResult, format_downloads, _game_version_key,
)
from ui.builds_page import (
    BuildsPage, monogram, PAGE_SIZE, ALL_GAME_VERSIONS,
    IconLoader, ModpackCard, rounded_pixmap,
)

app = QApplication.instance() or QApplication(sys.argv)

TOTAL = 35


def make_hit(index: int) -> ModpackHit:
    return ModpackHit(
        project_id=f"proj{index}",
        slug=f"pack-{index}",
        title=f"Pack {index}",
        description=f"Description {index}",
        author="Tester",
        downloads=1000 + index,
        follows=10 + index,
        icon_url="",
        categories=["adventure", "fabric"],
        game_versions=["1.20.1", "1.21.1"],
        loaders=["fabric"],
        latest_version="v1",
        date_updated="2024-01-01T00:00:00Z",
    )


class StubClient:
    """In-memory replacement for ModrinthCatalogClient."""

    provider_name = "Stub"
    sort_options = [("relevance", "Релевантность"), ("downloads", "Загрузки")]

    def __init__(self):
        self.tags = ModpackTags(
            game_versions=["1.21.1", "1.20.1"],
            categories=["adventure", "technology"],
            loaders=["fabric", "forge"],
        )
        self.search_calls = []
        self.detail_calls = []

    def get_tags(self, force=False):
        return self.tags

    def search(self, query="", game_version="", category="", loader="",
               sort="relevance", limit=20, offset=0, categories=None):
        self.search_calls.append({
            "query": query, "game_version": game_version, "category": category,
            "loader": loader, "sort": sort, "offset": offset,
            "categories": list(categories or []),
        })
        hits = [make_hit(i) for i in range(offset, min(offset + limit, TOTAL))]
        return SearchResult(hits=hits, total=TOTAL, offset=offset)

    def get_details(self, project_key, game_version="", loader=""):
        self.detail_calls.append(project_key)
        versions = [
            ModpackVersionInfo(
                id="v1", name="Pack 0 1.21.1", version_number="1.2.3",
                version_type="release", game_versions=["1.21.1"],
                loaders=["fabric"], date_published="2024-02-01T00:00:00Z",
                downloads=5000, files=[],
            ),
            ModpackVersionInfo(
                id="v0", name="Pack 0 1.20.1", version_number="1.0.0",
                version_type="release", game_versions=["1.20.1"],
                loaders=["fabric"], date_published="2023-01-01T00:00:00Z",
                downloads=100, files=[],
            ),
        ]
        return ModpackDetail(
            project_id="proj0", slug="pack-0", title="Pack 0",
            description="Full description", body="body", icon_url="",
            downloads=12345, follows=99, categories=["adventure", "fabric"],
            loaders=["fabric"], game_versions=["1.20.1", "1.21.1"],
            date_updated="2024-02-01T00:00:00Z", versions=versions,
        )


def pump(predicate, timeout=5.0):
    """Run the event loop until predicate() is true or the timeout elapses."""
    start = time.time()
    while time.time() - start < timeout:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def idle(page):
    """No background request threads left running."""
    catalog = page.modrinth
    threads = [catalog._tags_thread, catalog._search_thread, page._detail_thread]
    return all(t is None or not t.isRunning() for t in threads)


# --------------------------------------------------------------------------

def test_swiper():
    print("=" * 60)
    print("TEST 1: Provider swiper")
    print("=" * 60)
    page = BuildsPage(client=StubClient(), curseforge_client=StubClient())
    page.resize(1100, 700)

    ok = page.provider_stack.currentIndex() == 0
    ok = ok and page.swiper_buttons[0].isChecked()

    page._set_provider(1)
    ok = ok and page.provider_stack.currentIndex() == 1
    ok = ok and page.swiper_buttons[1].isChecked()
    ok = ok and not page.swiper_buttons[0].isChecked()

    page._set_provider(2)
    ok = ok and page.provider_stack.currentIndex() == 2

    page._set_provider(0)
    ok = ok and page.provider_stack.currentIndex() == 0

    print(f"  provider stack index: {page.provider_stack.currentIndex()}")
    print(f"  swiper button count : {len(page.swiper_buttons)}")
    print("[PASS] swiper switches provider screens" if ok else "[FAIL] swiper broken")
    page.shutdown()
    return ok


def test_catalog_load_and_filters():
    print("\n" + "=" * 60)
    print("TEST 2: Modrinth catalog load + filters")
    print("=" * 60)
    client = StubClient()
    page = BuildsPage(client=client, curseforge_client=StubClient())
    page.resize(1100, 700)

    page.ensure_loaded()
    loaded = pump(lambda: page.modrinth._cards and idle(page))

    catalog = page.modrinth
    ok = loaded
    ok = ok and len(catalog._cards) == PAGE_SIZE
    ok = ok and not catalog.more_button.isHidden()
    print(f"  cards after first page: {len(catalog._cards)} (expected {PAGE_SIZE})")

    # tags populate the filters panel
    ok = ok and catalog.filters.game_combo.count() == len(client.tags.game_versions) + 1
    ok = ok and len(catalog.filters._category_boxes) == len(client.tags.categories)
    ok = ok and len(catalog.filters._loader_buttons) == len(client.tags.loaders)
    print(f"  game versions        : {catalog.filters.game_combo.count()}")
    print(f"  category checkboxes  : {len(catalog.filters._category_boxes)}")
    print(f"  loader chips         : {len(catalog.filters._loader_buttons)}")

    # first search had no filters
    first = client.search_calls[0]
    ok = ok and first["game_version"] == "" and first["category"] == ""

    # changing the game version filter triggers a filtered search
    index = catalog.filters.game_combo.findData("1.21.1")
    catalog.filters.game_combo.setCurrentIndex(index)
    pump(lambda: idle(page) and len(client.search_calls) >= 2)
    last = client.search_calls[-1]
    ok = ok and last["game_version"] == "1.21.1"
    print(f"  filter search params : game={last['game_version']!r}")

    # loader filter (single-select chips)
    catalog.filters.select_loader("forge")
    pump(lambda: idle(page) and client.search_calls[-1]["loader"] == "forge")
    ok = ok and client.search_calls[-1]["loader"] == "forge"

    # category filter (multi-select checkboxes)
    catalog.filters.set_category("technology", True)
    catalog._on_filters_changed()
    pump(lambda: idle(page) and client.search_calls[-1]["categories"] == ["technology"])
    ok = ok and client.search_calls[-1]["categories"] == ["technology"]

    print("[PASS] catalog loads and filters reach the API"
          if ok else "[FAIL] catalog/filters broken")
    page.shutdown()
    return ok


def test_search_and_more():
    print("\n" + "=" * 60)
    print("TEST 3: Debounced search + 'Показать ещё'")
    print("=" * 60)
    client = StubClient()
    page = BuildsPage(client=client, curseforge_client=StubClient())
    page.resize(1100, 700)
    page.ensure_loaded()
    pump(lambda: page.modrinth._cards and idle(page))

    catalog = page.modrinth

    # typing only schedules the debounced request
    calls_before = len(client.search_calls)
    page.search_input.setText("create")
    ok = len(client.search_calls) == calls_before  # not fired yet
    pump(lambda: client.search_calls[-1]["query"] == "create")
    ok = ok and client.search_calls[-1]["query"] == "create"
    print(f"  debounced query      : {client.search_calls[-1]['query']!r}")

    # load more appends the next page
    total_after_first = len(catalog._cards)
    catalog.more_button.click()
    pump(lambda: idle(page) and len(catalog._cards) > total_after_first)
    ok = ok and len(catalog._cards) == TOTAL
    ok = ok and catalog.more_button.isHidden()
    print(f"  cards after 'more'   : {len(catalog._cards)} (expected {TOTAL})")

    print("[PASS] search debounce and pagination"
          if ok else "[FAIL] search/pagination broken")
    page.shutdown()
    return ok


def test_detail_navigation():
    print("\n" + "=" * 60)
    print("TEST 4: Detail screen navigation")
    print("=" * 60)
    client = StubClient()
    page = BuildsPage(client=client, curseforge_client=StubClient())
    page.resize(1100, 700)
    page.ensure_loaded()
    pump(lambda: page.modrinth._cards and idle(page))

    hit = page.modrinth._cards[0].hit
    page._open_detail(hit)
    ok = page.view_stack.currentIndex() == 1
    ok = ok and page.detail_view.title_label.text() == hit.title

    pump(lambda: idle(page) and page.detail_view._version_rows)
    ok = ok and len(page.detail_view._version_rows) == 2
    ok = ok and client.detail_calls == [hit.project_id]
    ok = ok and "Всего версий" in page.detail_view.versions_status.text()
    print(f"  detail title         : {page.detail_view.title_label.text()!r}")
    print(f"  version rows         : {len(page.detail_view._version_rows)}")
    print(f"  download button on   : {page.detail_view.install_button.isEnabled()} (expected False)")

    # back to catalog
    page.detail_view.back_requested.emit()
    ok = ok and page.view_stack.currentIndex() == 0

    print("[PASS] detail screen opens, loads versions and returns"
          if ok else "[FAIL] detail navigation broken")
    page.shutdown()
    return ok


def test_core_helpers():
    print("\n" + "=" * 60)
    print("TEST 5: Core helpers")
    print("=" * 60)

    ok = format_downloads(999) == "999"
    ok = ok and format_downloads(1500) == "1.5 тыс."
    ok = ok and format_downloads(2_000_000) == "2 млн"
    print(f"  format_downloads     : {format_downloads(1500)!r}, {format_downloads(2_000_000)!r}")

    ok = ok and monogram("Melon Vanilla+") == "MV"
    ok = ok and monogram("Create Adventure") == "CA"
    ok = ok and monogram("Solo") == "SO"
    print(f"  monogram             : {monogram('Melon Vanilla+')!r}, {monogram('Solo')!r}")

    ok = ok and _game_version_key("1.21.1") > _game_version_key("1.20.4")
    ok = ok and _game_version_key("26.3") > _game_version_key("1.21.1")

    hit = ModpackHit.from_hit({
        "project_id": "p", "slug": "s", "title": "T", "description": "d",
        "author": "a", "downloads": 5, "follows": 1, "icon_url": "",
        "categories": ["adventure", "neoforge"], "versions": ["1.20.1", "1.21.1"],
        "latest_version": "v", "date_modified": "2024-01-01",
    })
    ok = ok and hit.primary_loader == "NeoForge"
    ok = ok and hit.latest_game_version == "1.21.1"
    ok = ok and hit.key == "s"
    print(f"  hit loader/latest    : {hit.primary_loader!r}, {hit.latest_game_version!r}")

    # facets are built correctly by the real client (network stubbed out)
    captured = {}

    class FacetClient(ModrinthCatalogClient):
        def _get(self, path, params=None):
            captured["params"] = params
            return {"hits": [], "total_hits": 0}

    FacetClient().search(query="x", game_version="1.21.1",
                         category="adventure", loader="fabric", sort="downloads")
    facets = captured["params"]["facets"]
    ok = ok and '"project_type:modpack"' in facets
    ok = ok and '"versions:1.21.1"' in facets
    ok = ok and '"categories:adventure"' in facets
    ok = ok and '"categories:fabric"' in facets
    ok = ok and captured["params"]["index"] == "downloads"
    ok = ok and captured["params"]["query"] == "x"
    print(f"  facets               : {facets}")

    # multiple categories are OR-ed into a single facet group
    FacetClient().search(categories=["adventure", "technology"])
    multi = captured["params"]["facets"]
    ok = ok and '"categories:adventure"' in multi
    ok = ok and '"categories:technology"' in multi
    print(f"  multi-category facets: {multi}")

    print("[PASS] core helpers correct" if ok else "[FAIL] core helpers broken")
    return ok


def test_shutdown():
    print("\n" + "=" * 60)
    print("TEST 6: shutdown() stops threads")
    print("=" * 60)
    page = BuildsPage(client=StubClient(), curseforge_client=StubClient())
    page.resize(1100, 700)
    page.ensure_loaded()
    page.shutdown()
    ok = page.modrinth._tags_thread is None and page.modrinth._search_thread is None
    ok = ok and page._detail_thread is None
    print(f"  tags/search/detail   : {page.modrinth._tags_thread}, "
          f"{page.modrinth._search_thread}, {page._detail_thread}")
    print("[PASS] threads stopped" if ok else "[FAIL] threads still running")
    return ok


def test_icon_covers():
    print("\n" + "=" * 60)
    print("TEST 7: Modpack cover loading")
    print("=" * 60)
    import tempfile
    from PyQt6.QtGui import QPixmap, QColor

    ok = True

    # rounded_pixmap scales-to-fill, crops to the exact size and rounds corners
    source = QPixmap(64, 32)
    source.fill(QColor("#ff0000"))
    rounded = rounded_pixmap(source, 40, 40, 12)
    ok = ok and rounded is not None
    ok = ok and rounded.width() == 40 and rounded.height() == 40
    ok = ok and rounded.toImage().pixelColor(0, 0).alpha() == 0
    print(f"  rounded_pixmap       : {rounded.width()}x{rounded.height()} "
          f"(corner alpha={rounded.toImage().pixelColor(0, 0).alpha()})")

    with tempfile.TemporaryDirectory() as tmp:
        loader = IconLoader(tmp)
        cover_url = "http://example.test/cover.png"

        # A cover already in the cache is delivered without touching the network.
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor("#00ff00"))
        loader._cache[cover_url] = pixmap

        received = {}
        loader.icon_ready.connect(lambda url, p: received.update({url: p}))
        loader.request(cover_url)
        ok = ok and pump(lambda: cover_url in received)
        print(f"  cached cover emitted : {cover_url in received}")

        # An empty url is a no-op (and must not start a download).
        before = len(received)
        loader.request("")
        app.processEvents()
        ok = ok and len(received) == before

        # A catalog card swaps its monogram for the cover when it arrives.
        hit = make_hit(0)
        hit = ModpackHit(
            project_id="cover", slug="cover", title="Cover Pack",
            description="d", author="a", downloads=1, follows=1,
            icon_url=cover_url, categories=["fabric"],
            game_versions=["1.21.1"], loaders=["fabric"],
            latest_version="v", date_updated="2024-01-01",
        )
        card = ModpackCard(hit)
        card.bind_icon(loader)
        ok = ok and pump(lambda: card.preview._cover is not None)
        print(f"  card cover applied   : {card.preview._cover is not None}")

        loader.shutdown()

    print("[PASS] covers load from cache and reach the widgets"
          if ok else "[FAIL] cover loading broken")
    return ok


def test_curseforge_mapping():
    print("\n" + "=" * 60)
    print("TEST 8: CurseForge mapping (offline)")
    print("=" * 60)

    from core.curseforge_catalog import CurseForgeCatalogClient

    mod = {
        "id": 999, "slug": "cool-pack", "name": "Cool Pack",
        "summary": "Great pack", "downloadCount": 1234567, "thumbsUpCount": 42,
        "authors": [{"name": "Author"}],
        "logo": {"thumbnailUrl": "https://media.forgecdn.net/thumb.png"},
        "categories": [{"name": "Adventure"}],
        "dateModified": "2024-05-01T10:00:00Z",
        "latestFiles": [
            {"displayName": "Cool Pack 1.1", "gameVersions": ["1.21.1", "Fabric"]},
        ],
    }

    class FakeClient(CurseForgeCatalogClient):
        def __init__(self):
            super().__init__(api_key="test")
            self.calls = []

        def _get(self, path, params=None):
            self.calls.append((path, params))
            if path == "/v1/mods/search":
                return {"data": [mod], "pagination": {"totalCount": 7, "index": 0}}
            if path == "/v1/mods/999":
                return {"data": mod}
            if path == "/v1/mods/999/description":
                return {"data": "<p>Desc</p>"}
            if path == "/v1/mods/999/files":
                return {"data": [{
                    "id": 555, "displayName": "Cool Pack 1.1", "fileName": "cool.zip",
                    "releaseType": 1, "gameVersions": ["1.21.1", "Fabric"],
                    "fileDate": "2024-05-01T10:00:00Z", "downloadCount": 10,
                    "downloadUrl": "https://edge.forgecdn.net/cool.zip",
                    "fileLength": 2048,
                }]}
            if path == "/v1/minecraft/version":
                return {"data": [
                    {"versionString": "1.21.1"},
                    {"versionString": "1.20.4"},
                    {"versionString": "1.21.6-snapshot"},
                ]}
            if path == "/v1/categories":
                return {"data": [
                    {"id": 4475, "name": "Adventure", "classId": 4471},
                    {"id": 4476, "name": "Tech", "classId": 4471},
                    {"id": 6, "name": "Other", "classId": 6},
                ]}
            return {}

    client = FakeClient()
    ok = True

    tags = client.get_tags()
    ok = ok and tags.game_versions == ["1.21.1", "1.20.4"]
    ok = ok and tags.categories == ["Adventure", "Tech"]
    ok = ok and set(tags.loaders) == {"fabric", "forge", "quilt", "neoforge"}
    print(f"  tags   : versions={tags.game_versions} categories={tags.categories}")

    result = client.search(query="cool", game_version="1.21.1",
                           category="Adventure", loader="fabric", sort="downloads")
    ok = ok and result.total == 7 and len(result.hits) == 1
    hit = result.hits[0]
    ok = ok and hit.title == "Cool Pack" and hit.author == "Author"
    ok = ok and hit.icon_url.endswith("thumb.png")
    ok = ok and hit.primary_loader == "Fabric"
    ok = ok and hit.latest_game_version == "1.21.1"
    ok = ok and hit.downloads == 1234567
    print(f"  hit    : {hit.title!r} loader={hit.primary_loader} "
          f"latest={hit.latest_game_version}")

    params = next(p for path, p in client.calls if path == "/v1/mods/search")
    ok = ok and params["gameId"] == 432 and params["classId"] == 4471
    ok = ok and params["searchFilter"] == "cool"
    ok = ok and params["gameVersion"] == "1.21.1"
    ok = ok and params["modLoaderType"] == 4
    ok = ok and params["categoryId"] == 4475
    ok = ok and params["sortField"] == 6 and params["sortOrder"] == "desc"
    print(f"  params : gameId={params['gameId']} loader={params['modLoaderType']} "
          f"cat={params['categoryId']} sortField={params['sortField']}")

    detail = client.get_details("999")
    ok = ok and detail.title == "Cool Pack"
    ok = ok and detail.body == "<p>Desc</p>"
    ok = ok and detail.follows == 42
    ok = ok and len(detail.versions) == 1
    version = detail.versions[0]
    ok = ok and version.version_type == "release"
    ok = ok and version.loader_label == "Fabric"
    ok = ok and version.files[0]["url"].endswith("cool.zip")
    print(f"  detail : versions={len(detail.versions)} type={version.version_type}")

    print("[PASS] CurseForge payloads map onto the shared model"
          if ok else "[FAIL] CurseForge mapping broken")
    return ok


def test_discover_page_switching():
    print("\n" + "=" * 60)
    print("TEST 9: CurseForge home <-> results switching")
    print("=" * 60)
    page = BuildsPage(client=StubClient(), curseforge_client=StubClient())
    page.resize(1100, 700)
    page.show()

    ok = True
    page._set_provider(1)
    catalog = page.curseforge
    pump(lambda: catalog.discover._loaded and not catalog.discover._thread.isRunning())

    # home is shown, the results list is not
    ok = ok and catalog.stack.currentWidget() is catalog.discover
    ok = ok and not catalog.discover.isHidden() and catalog.results.isHidden()
    print(f"  home    : discover_hidden={catalog.discover.isHidden()} "
          f"results_hidden={catalog.results.isHidden()}")

    # typing a query swaps to the results page (and only that page)
    page.search_input.setText("sky")
    pump(lambda: catalog.stack.currentWidget() is catalog.results)
    ok = ok and catalog.stack.currentWidget() is catalog.results
    ok = ok and catalog.results.isHidden() is False and catalog.discover.isHidden()
    print(f"  query   : discover_hidden={catalog.discover.isHidden()} "
          f"results_hidden={catalog.results.isHidden()}")

    # clearing the query goes back to the home page
    page.search_input.setText("")
    pump(lambda: catalog.stack.currentWidget() is catalog.discover)
    ok = ok and catalog.stack.currentWidget() is catalog.discover
    print(f"  cleared : current={catalog.stack.currentWidget().objectName() or 'discover'}")

    # "Все →" on the second section forces the results list even without query
    catalog._on_show_all("other")
    app.processEvents()
    ok = ok and catalog.stack.currentWidget() is catalog.results
    ok = ok and catalog.results.isHidden() is False and catalog.discover.isHidden()
    print(f"  show all: discover_hidden={catalog.discover.isHidden()} "
          f"results_hidden={catalog.results.isHidden()}")

    # switching providers always lands back on the home page
    page._set_provider(0)
    page._set_provider(1)
    app.processEvents()
    ok = ok and catalog.stack.currentWidget() is catalog.discover

    print("[PASS] only one catalog page is visible at a time"
          if ok else "[FAIL] catalog pages overlap")
    page.shutdown()
    page.close()
    return ok


def main():
    print("Melon Launcher - Stage 6 Acceptance Criteria Verification")
    print("=" * 60)

    results = [
        ("Provider swiper", test_swiper()),
        ("Modrinth catalog + filters", test_catalog_load_and_filters()),
        ("Debounced search + pagination", test_search_and_more()),
        ("Detail screen navigation", test_detail_navigation()),
        ("Core helpers", test_core_helpers()),
        ("shutdown()", test_shutdown()),
        ("Cover loading", test_icon_covers()),
        ("CurseForge mapping", test_curseforge_mapping()),
        ("Discover page switching", test_discover_page_switching()),
    ]

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        print(f"  {'[PASS]' if passed else '[FAIL]'}: {name}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All acceptance criteria PASSED")
        return 0
    print("Some acceptance criteria FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
