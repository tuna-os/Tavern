# Rollout Plan: Automated Flatpak OCI Remote

This plan outlines the steps required to fully roll out, enable, and verify the self-hosted Flatpak OCI remote for Tavern.

---

## 📅 Phases

### Phase 1: Code Review and Integration
- [x] **Review PR #29**: Inspect the Github Actions configuration and index update Python script.
- [x] **Merge PR #29**: Merge the `feature/flatpak-oci-remote` branch into `main`.

### Phase 2: Pipeline Execution & Registry Initialization
- [x] **Trigger Initial Build**: Merging to `main` will kick off the `Build and Publish Flatpak OCI` workflow.
- [x] **Verify OCI Push**: Ensure the OCI image is successfully built and pushed to `ghcr.io/tuna-os/tavern:latest`.
- [x] **Verify gh-pages Branch Creation**: Ensure the workflow successfully creates/commits to the `gh-pages` branch.

### Phase 3: Hosting Configuration
- [x] **Enable GitHub Pages**:
  1. Navigate to the repository Settings on GitHub.
  2. Select **Pages** from the sidebar.
  3. Set source to `Deploy from a branch`.
  4. Select `gh-pages` and `/ (root)` folder, then click **Save**.
- [x] **Verify Index Availability**: Confirm that `https://tuna-os.github.io/Tavern/index/static` serves a valid JSON index.

### Phase 4: Client Verification
- [x] **Uninstall Local Installations**: Clear any existing development/local builds of Tavern to prevent conflicts:
  ```bash
  flatpak uninstall --user dev.hanthor.Tavern
  ```
- [x] **Test Remote Installation**: Add the OCI remote and install the application from it:
  ```bash
  flatpak remote-add --user --if-not-exists tuna-os oci+https://tuna-os.github.io/Tavern
  flatpak install --user tuna-os dev.hanthor.Tavern
  ```
- [x] **Verify App Execution**: Launch the app installed from the OCI remote and verify it runs correctly.

### Phase 5: Update Flow Verification
- [x] **Trigger an Update**: Push a version tag (e.g. `v0.1.10`) or a dummy commit to `main`.
- [x] **Verify Update Pipeline**: Confirm that the workflow runs and updates the manifest digest in `index/static`.
- [x] **Test Client Update**: Run `flatpak update` on the client machine and confirm it pulls the update seamlessly.

### Phase 6: Documentation and Cleanup
- [x] **Update README.md**: Add installation instructions for the new OCI remote so users can install and receive automatic updates.
- [x] **Clean Up Dev Branches**: Safely delete the remote `feature/flatpak-oci-remote` branch.
