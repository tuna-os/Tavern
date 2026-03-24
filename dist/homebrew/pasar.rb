cask "pasar" do
  version "0.1.0"
  sha256 :no_check

  url "https://github.com/hanthor/Pasar/releases/download/v#{version}/Pasar-macOS.zip"
  name "Pasar"
  desc "Homebrew App Store for macOS/GNOME"
  homepage "https://github.com/hanthor/Pasar"

  depends_on formula: "gtk4"
  depends_on formula: "libadwaita"
  depends_on formula: "blueprint-compiler"
  depends_on formula: "python@3.12"

  app "Pasar.app"

  zap trash: [
    "~/.cache/pasar",
    "~/.local/share/pasar",
    "~/.local/bin/pasar",
  ]
end
