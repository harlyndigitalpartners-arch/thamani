"""Real subprocess/protocol round trip against the borrowed filesystem server."""
import shutil
from pathlib import Path

import pytest

from src.agent.loop import FilesystemMCPClient


SERVER = Path(__file__).resolve().parents[1] / "tools/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"


@pytest.mark.skipif(not SERVER.is_file() or not shutil.which("node"), reason="Install Node and npm ci --prefix tools/filesystem")
def test_filesystem_mcp_writes_and_preserves_archive(tmp_path):
    client = FilesystemMCPClient(tmp_path)
    saved = client.write_file("roundtrip.md", "# MCP protocol round trip\n")
    assert saved.read_text(encoding="utf-8") == "# MCP protocol round trip\n"
    with pytest.raises(FileExistsError):
        client.write_file("roundtrip.md", "Changed archive")
