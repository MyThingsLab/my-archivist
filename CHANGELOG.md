# Changelog

## [Unreleased]
### Added/Changed
- Pilot migration to mythings.testing: dropped local ScriptedEngine/SpyEngine/FakeRunner/git-builder/fetch fakes; the stateful gh double became FakeGh with closure handlers (fake_gh), empty_fetch/fake_fetch_factory became fake_fetch wiring, make_repo/read_committed delegate to make_git_repo/GitRepo; EPUB/PDF/OpenLibrary payload builders stay local. clean_git_env re-exported via aliased import + getfixturevalue autouse wrapper (pytest registers imported fixtures under the attribute name; ruff F811 forbids the shadowing-param wrapper).
