# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for visual evidence recording, manifest generation, and acceptance oracle."""

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tools.tests.loader import load_module

ve = load_module("tools/visual_evidence.py", "visual_evidence")


def make_dummy_png(path: Path, width: int = 1000, height: int = 700, fill_byte: int = 0xAA) -> Path:
    """Create a minimal valid PNG file on disk for test fixtures."""
    # PNG signature: 8 bytes
    sig = b"\x89PNG\r\n\x1a\n"

    # IHDR chunk: 13 bytes data (width 4, height 4, depth 1, color_type 1, comp 1, filt 1, interlace 1)
    ihdr_data = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 2, 0, 0, 0])  # 8-bit truecolor RGB
    )
    ihdr_crc = hashlib.md5(ihdr_data).digest()[:4]
    ihdr_chunk = len(ihdr_data).to_bytes(4, "big") + b"IHDR" + ihdr_data + ihdr_crc

    # Diverse payload to simulate multiple colors
    payload = bytes([fill_byte, (fill_byte + 1) % 256, (fill_byte + 2) % 256, 0x11, 0x22, 0x33, 0x44, 0x55] * 200)
    idat_crc = hashlib.md5(payload).digest()[:4]
    idat_chunk = len(payload).to_bytes(4, "big") + b"IDAT" + payload + idat_crc

    # IEND chunk
    iend_chunk = (0).to_bytes(4, "big") + b"IEND" + b"\xae\x42\x60\x82"

    path.write_bytes(sig + ihdr_chunk + idat_chunk + iend_chunk)
    return path


# ─── 1. Acceptance Oracle Tests (Criterion 6) ────────────────────────────────


def test_oracle_positive_control_candidate_passes(tmp_path):
    img = make_dummy_png(tmp_path / "candidate.png")
    frame_info = ve.inspect_png_file(img)
    run_start = datetime.now(timezone.utc).isoformat()

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=run_start,
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="app/org.tunaos.tavern/x86_64/master",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="68a0051",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="runtime_sha_123",
        binary_digest="sha256:candidate_digest_456",
        source_commit="commit_pr_789",
        capture_action_ref="tuna-os/flatpak-index/.github/actions/capture-screenshots@9b8dada",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={
            "banner_revealed": True,
            "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT,
            "content_stack_child": "main",
            "frozen_loading_detected": False,
            "error_screen_detected": False,
        },
        frames=[frame_info],
    )

    run_context = {
        "expected_binary_digest": "candidate_digest_456",
        "expected_source_commit": "commit_pr_789",
        "expected_runtime_commit": "runtime_sha_123",
    }
    result = ve.evaluate_acceptance(receipt, run_context=run_context)
    assert result["passed"] is True
    assert "Positive control passed" in result["reason"]


def test_oracle_positive_control_published_passes(tmp_path):
    img = make_dummy_png(tmp_path / "published.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_PUBLISHED,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="999",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="app/org.tunaos.tavern/x86_64/stable",
        architecture="x86_64",
        remote="tuna-os",
        app_commit="prod_commit_111",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="runtime_sha_123",
        binary_digest="not-applicable",
        source_commit="unknown",
        capture_action_ref="tuna-os/flatpak-index/.github/actions/capture-screenshots@9b8dada",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={
            "banner_revealed": True,
            "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT,
            "content_stack_child": "main",
            "frozen_loading_detected": False,
            "error_screen_detected": False,
        },
        frames=[frame_info],
    )

    result = ve.evaluate_acceptance(receipt)
    assert result["passed"] is True
    assert "Positive control passed" in result["reason"]


def test_oracle_rejects_published_substituted_for_candidate(tmp_path):
    img = make_dummy_png(tmp_path / "subst.png")
    frame_info = ve.inspect_png_file(img)

    # Candidate lane, but artifact is published shape
    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="app/org.tunaos.tavern/x86_64/master",
        architecture="x86_64",
        remote="tuna-os",  # Error: remote is tuna-os in candidate lane
        app_commit="prod_commit",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="rc",
        binary_digest="not-applicable",
        source_commit="unknown",  # Error: unknown source in candidate lane
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    res = ve.evaluate_acceptance(receipt)
    assert res["passed"] is False
    assert "published package substituted for candidate" in res["reason"]


def test_oracle_rejects_wrong_binary_and_source_digest(tmp_path):
    img = make_dummy_png(tmp_path / "wrong.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="app/org.tunaos.tavern/x86_64/master",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="68a0051",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="actual_runtime_1",
        binary_digest="sha256:actual_bundle_abc",
        source_commit="actual_commit_pr1",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    # Mismatch binary digest
    res = ve.evaluate_acceptance(receipt, run_context={"expected_binary_digest": "different_bundle_xyz"})
    assert res["passed"] is False
    assert "binary digest mismatch" in res["reason"]

    # Mismatch source commit
    res2 = ve.evaluate_acceptance(receipt, run_context={"expected_source_commit": "expected_commit_pr2"})
    assert res2["passed"] is False
    assert "source commit mismatch" in res2["reason"]

    # Mismatch runtime commit
    res3 = ve.evaluate_acceptance(receipt, run_context={"expected_runtime_commit": "expected_runtime_2"})
    assert res3["passed"] is False
    assert "runtime commit mismatch" in res3["reason"]


def test_oracle_rejects_wrong_app_id(tmp_path):
    img = make_dummy_png(tmp_path / "calc.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.gnome.Calculator",  # Not Tavern
        ref="app/org.gnome.Calculator/x86_64/stable",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="68a0051",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.gnome.Calculator",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    res = ve.evaluate_acceptance(receipt)
    assert res["passed"] is False
    assert "wrong app/runtime or source digest: app_id 'org.gnome.Calculator' not allowed" in res["reason"]


def test_oracle_rejects_stale_png(tmp_path):
    img = make_dummy_png(tmp_path / "stale.png")
    frame_info = ve.inspect_png_file(img)

    # Set frame mtime in the past
    past_time = time.time() - 3600
    os.utime(img, (past_time, past_time))
    frame_info["mtime"] = past_time

    # Run started at now
    run_started = datetime.now(timezone.utc).isoformat()

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=run_started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="app/org.tunaos.tavern/x86_64/master",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="68a0051",
        runtime="org.gnome.Platform/x86_64/50",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    res = ve.evaluate_acceptance(receipt)
    assert res["passed"] is False
    assert "stale PNG" in res["reason"]

    # Also test known stale hash rejection
    res2 = ve.evaluate_acceptance(receipt, run_context={"known_stale_hashes": [frame_info["sha256"]]})
    assert res2["passed"] is False
    assert "matches stale baseline" in res2["reason"]


def test_oracle_rejects_unrelated_window(tmp_path):
    img = make_dummy_png(tmp_path / "xclock.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=False,  # Unrelated window
        window_wm_class="xclock",  # Unrelated class
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    res = ve.evaluate_acceptance(receipt)
    assert res["passed"] is False
    assert "unrelated window" in res["reason"]


def test_oracle_rejects_frozen_loading_and_error_screen(tmp_path):
    img = make_dummy_png(tmp_path / "frozen.png")
    frame_info = ve.inspect_png_file(img)

    # 1. Stuck on loading
    receipt_loading = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={
            "banner_revealed": True,
            "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT,
            "content_stack_child": "loading",
            "frozen_loading_detected": True,
        },
        frames=[frame_info],
    )
    res1 = ve.evaluate_acceptance(receipt_loading)
    assert res1["passed"] is False
    assert "frozen loading/error screen" in res1["reason"]

    # 2. Error screen presented
    receipt_error = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={
            "banner_revealed": True,
            "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT,
            "content_stack_child": "main",
            "error_screen_detected": True,
        },
        frames=[frame_info],
    )
    res2 = ve.evaluate_acceptance(receipt_error)
    assert res2["passed"] is False
    assert "frozen loading/error screen: error screen presented to user" in res2["reason"]


def test_oracle_rejects_missing_expected_no_homebrew_message(tmp_path):
    img = make_dummy_png(tmp_path / "missing_banner.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={
            "banner_revealed": False,  # Banner not revealed in no-homebrew!
            "banner_text": "",
            "content_stack_child": "main",
        },
        frames=[frame_info],
    )

    res = ve.evaluate_acceptance(receipt)
    assert res["passed"] is False
    assert "missing expected no-Homebrew message" in res["reason"]


def test_oracle_rejects_missing_failed_capture(tmp_path):
    # 1. Failed status
    receipt_failed = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="failed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=False,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[],
        failures=["capture-app.sh timed out waiting for window"],
    )
    res1 = ve.evaluate_acceptance(receipt_failed)
    assert res1["passed"] is False
    assert "missing or failed capture" in res1["reason"]

    # 2. Blank capture (< 8 colors)
    frame_blank = {
        "name": "blank.png",
        "path": "/tmp/blank.png",
        "geometry": "1000x700",
        "colors": 2,  # Window never painted
        "sha256": "blankhash",
    }
    receipt_blank = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="123",
        run_attempt=1,
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:abc",
        source_commit="def",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_blank],
    )
    res2 = ve.evaluate_acceptance(receipt_blank)
    assert res2["passed"] is False
    assert "window never painted" in res2["reason"]


# ─── 2. Directory and Manifest Tests (Criterion 3) ───────────────────────────


def test_prepare_run_directory_isolation(tmp_path):
    run_dir = ve.prepare_run_directory(tmp_path, ve.LANE_CANDIDATE, run_id="run42", run_attempt=1)
    assert run_dir.is_dir()
    assert run_dir.name == "candidate-artifact-run-run42-1"

    # Put a leftover file in it
    (run_dir / "old_leftover.png").write_text("old")

    # Calling prepare_run_directory again cleans up prior leftovers
    fresh_dir = ve.prepare_run_directory(tmp_path, ve.LANE_CANDIDATE, run_id="run42", run_attempt=1)
    assert not (fresh_dir / "old_leftover.png").exists()


def test_generate_manifest_records_all_artifacts(tmp_path):
    run_dir = ve.prepare_run_directory(tmp_path, ve.LANE_PUBLISHED, run_id="55", run_attempt=1)
    img = make_dummy_png(run_dir / "main.png")
    (run_dir / "receipt.json").write_text(json.dumps({"test": 1}))
    (run_dir / "run.log").write_text("log content")

    manifest = ve.generate_manifest(run_dir, run_id="55", run_attempt=1)
    assert manifest["manifest_version"] == "1.0"
    assert manifest["run_id"] == "55"
    assert manifest["run_attempt"] == 1
    artifacts = {a["name"]: a for a in manifest["artifacts"]}

    assert "main.png" in artifacts
    assert artifacts["main.png"]["type"] == "image/png"
    assert len(artifacts["main.png"]["sha256"]) == 64

    assert "receipt.json" in artifacts
    assert artifacts["receipt.json"]["type"] == "application/json"

    assert "run.log" in artifacts
    assert artifacts["run.log"]["type"] == "text/plain"

    # manifest file itself exists on disk
    assert (run_dir / "artifacts-manifest.json").exists()


# ─── 3. Receipt Redaction and Allowlisting Tests (Criterion 7) ───────────────


def test_receipt_redaction_and_untested_configurations(tmp_path):
    img = make_dummy_png(tmp_path / "img.png")
    frame_info = ve.inspect_png_file(img)

    receipt = ve.build_receipt(
        lane=ve.LANE_CANDIDATE,
        scenario=ve.SCENARIO_NO_HOMEBREW,
        status="passed",
        run_id="1",
        run_attempt=1,
        started_at="2026-10-31T00:00:00Z",
        completed_at="2026-10-31T00:00:10Z",
        app_id="org.tunaos.tavern",
        ref="ref",
        architecture="x86_64",
        remote="local-candidate-build",
        app_commit="c",
        runtime="r",
        runtime_commit="rc",
        binary_digest="sha256:123",
        source_commit="456",
        capture_action_ref="action",
        runner_os="Linux",
        display=":99",
        geometry="1000x700",
        scale=1,
        locale="C.UTF-8",
        renderer="software",
        homebrew_available=False,
        fixture_state="explicit-no-homebrew",
        window_owned=True,
        window_wm_class="org.tunaos.tavern",
        readiness_verified=True,
        scenario_assertions={"banner_revealed": True, "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT},
        frames=[frame_info],
    )

    # Convert to json and verify no secrets or unredacted keys
    serialized = json.dumps(receipt)
    assert "token" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "secret" not in serialized.lower()

    # Verify untested configurations are documented
    coverage = receipt["coverage"]
    assert "freshness" in coverage
    assert "real-supported-host-with-homebrew" in coverage["untested_supported_configurations"]
    assert "macos-native-cask" in coverage["untested_supported_configurations"]


# ─── 4. Parsing and Inspection Tests ─────────────────────────────────────────


def test_parse_flatpak_info():
    sample_info = """
Tavern - A Homebrew App Store for GNOME

          ID: org.tunaos.tavern
         Ref: app/org.tunaos.tavern/x86_64/master
        Arch: x86_64
      Branch: master
     Version: 0.1.65
     License: GPL-3.0-or-later
      Origin: tuna-os
  Collection: 
Installation: user
   Installed: 42.5 MB
     Runtime: org.gnome.Platform/x86_64/50
         Sdk: org.gnome.Sdk/x86_64/50

      Commit: 68a00516914b2c4857c8a221c3784210feae8aa7
      Parent: 73d41010a08e0da7715b0451f2f81498bfe1b9db
      Subject: fix(ci): pin compatible pytest benchmark dependencies (#313)
        Date: 2026-10-30 20:53:14 +0000
    """
    parsed = ve.parse_flatpak_info(sample_info)
    assert parsed["app_id"] == "org.tunaos.tavern"
    assert parsed["ref"] == "app/org.tunaos.tavern/x86_64/master"
    assert parsed["architecture"] == "x86_64"
    assert parsed["branch"] == "master"
    assert parsed["version"] == "0.1.65"
    assert parsed["remote"] == "tuna-os"
    assert parsed["app_commit"] == "68a00516914b2c4857c8a221c3784210feae8aa7"
    assert parsed["runtime"] == "org.gnome.Platform/x86_64/50"


def test_inspect_png_file_validates_dimensions(tmp_path):
    img = make_dummy_png(tmp_path / "valid.png", width=1000, height=700)
    info = ve.inspect_png_file(img)
    assert info["width"] == 1000
    assert info["height"] == 700
    assert info["geometry"] == "1000x700"
    assert info["colors"] >= 8
    assert len(info["sha256"]) == 64


# ─── 5. CLI Execution ─────────────────────────────────────────────────────────


def test_cli_record_and_evaluate(tmp_path):
    out_dir = tmp_path / "out"
    img = make_dummy_png(tmp_path / "test.png")

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "application_id": "org.tunaos.tavern",
        "scenario": "no-homebrew",
        "banner_revealed": True,
        "banner_text": ve.EXPECTED_NO_HOMEBREW_TEXT,
        "content_stack_child": "main",
        "is_loading": False,
        "homebrew_available": False,
    }))

    # Run record
    record_cmd = [
        sys.executable,
        str(Path(ve.__file__).resolve()),
        "record",
        "--lane", ve.LANE_CANDIDATE,
        "--scenario", ve.SCENARIO_NO_HOMEBREW,
        "--out-dir", str(out_dir),
        "--image", str(img),
        "--app-id", "org.tunaos.tavern",
        "--source-commit", "sha_source_1",
        "--binary-digest", "sha256:sha_binary_1",
        "--run-id", "101",
        "--run-attempt", "1",
        "--state-file", str(state_file),
    ]
    res_rec = subprocess.run(record_cmd, capture_output=True, text=True)
    assert res_rec.returncode == 0, res_rec.stderr
    assert (out_dir / "receipt.json").exists()
    assert (out_dir / "artifacts-manifest.json").exists()

    # Run evaluate
    eval_cmd = [
        sys.executable,
        str(Path(ve.__file__).resolve()),
        "evaluate",
        "--receipt", str(out_dir / "receipt.json"),
        "--manifest", str(out_dir / "artifacts-manifest.json"),
        "--expected-binary-digest", "sha_binary_1",
        "--expected-source-commit", "sha_source_1",
    ]
    res_ev = subprocess.run(eval_cmd, capture_output=True, text=True)
    assert res_ev.returncode == 0, res_ev.stderr
    assert "ACCEPTANCE PASSED" in res_ev.stdout
