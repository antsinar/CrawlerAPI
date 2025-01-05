from enum import StrEnum
from pathlib import Path

GRAPH_ROOT = Path(__file__).parent.parent / "graphs"
LOGS_ROOT = Path(__file__).parent.parent / "logs"


class Compressor(StrEnum):
    GZIP = "gzip"
    LZMA = "lzma"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


distance_ranges = {
    Difficulty.EASY: range(0, 1000),
    Difficulty.MEDIUM: range(1000, 10000),
    Difficulty.HARD: range(10000, 100000),
}

compressor_extensions = {Compressor.GZIP.value: ".gz", Compressor.LZMA.value: ".xz"}

HTTP_SCHEME = "http://"
HTTPS_SCHEME = "https://"
