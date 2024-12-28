from enum import StrEnum
from pathlib import Path

GRAPH_ROOT = Path(__file__).parent.parent / "graphs"
LOGS_ROOT = Path(__file__).parent.parent / "logs"


class Compressor(StrEnum):
    GZIP = "gzip"
    LZMA = "lzma"


compressor_extensions = {Compressor.GZIP.value: ".gz", Compressor.LZMA.value: ".xz"}
