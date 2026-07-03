#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Update Flatpak OCI index file from local OCI layout.")
    parser.add_argument("--oci-dir", required=True, help="Path to local OCI layout directory")
    parser.add_argument("--index-file", default="index/static", help="Path to index/static file to update")
    parser.add_argument("--repo-name", required=True, help="Repository name on GHCR, e.g. tuna-os/tavern")
    parser.add_argument("--registry", default="ghcr.io")
    parser.add_argument("--tags", nargs="+", default=["latest"])
    args = parser.parse_args()

    oci_dir = Path(args.oci_dir)
    index_file = Path(args.index_file)

    # 1. Parse index.json in OCI layout to find manifest digest
    index_json_path = oci_dir / "index.json"
    if not index_json_path.exists():
        raise FileNotFoundError(f"index.json not found in {oci_dir}")

    with open(index_json_path) as f:
        oci_index = json.load(f)

    # Find manifest descriptor
    manifests = oci_index.get("manifests", [])
    if not manifests:
        raise ValueError("No manifests found in index.json")

    manifest_desc = manifests[0]
    manifest_digest = manifest_desc["digest"]  # sha256:hash
    manifest_hash = manifest_digest.split(":")[-1]

    # 2. Parse manifest JSON to find config digest
    manifest_path = oci_dir / "blobs" / "sha256" / manifest_hash
    with open(manifest_path) as f:
        manifest = json.load(f)

    config_desc = manifest["config"]
    config_digest = config_desc["digest"]
    config_hash = config_digest.split(":")[-1]

    # 3. Parse config JSON to extract architecture, os, and labels
    config_path = oci_dir / "blobs" / "sha256" / config_hash
    with open(config_path) as f:
        config = json.load(f)

    architecture = config.get("architecture", "amd64")
    os_ = config.get("os", "linux")
    labels = config.get("config", {}).get("Labels", {})

    # 4. Validate required Flatpak labels
    required_labels = ["org.flatpak.ref", "org.flatpak.metadata"]
    for label in required_labels:
        if label not in labels:
            raise ValueError(f"Missing required label: {label}")

    # 5. Load or initialize target index/static
    if index_file.exists():
        with open(index_file) as f:
            index_data = json.load(f)
    else:
        index_data = {
            "Registry": f"https://{args.registry}",
            "Results": []
        }

    # 6. Build new image entry
    image_entry = {
        "Digest": manifest_digest,
        "MediaType": "application/vnd.oci.image.manifest.v1+json",
        "OS": os_,
        "Architecture": architecture,
        "Tags": args.tags,
        "Labels": {
            k: v for k, v in labels.items() if k.startswith("org.flatpak.")
        }
    }

    # 7. Update or append result entry in index
    repo_found = False
    for result in index_data.get("Results", []):
        if result["Name"] == args.repo_name:
            repo_found = True
            # Replace existing entry for this architecture
            result["Images"] = [
                img for img in result["Images"] if img["Architecture"] != architecture
            ]
            result["Images"].append(image_entry)
            break

    if not repo_found:
        index_data.setdefault("Results", []).append({
            "Name": args.repo_name,
            "Images": [image_entry]
        })

    # 8. Write updated index/static
    index_file.parent.mkdir(parents=True, exist_ok=True)
    with open(index_file, "w") as f:
        json.dump(index_data, f, indent=2)
        f.write("\n")

    print(f"Successfully updated index file {index_file} with {args.repo_name} ({architecture})")

if __name__ == "__main__":
    main()
