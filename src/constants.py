from enum import Enum, StrEnum
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


class MoveOptions(Enum):
    ONE_HUNDRED = 100
    TWO_HUNDRED = 200
    FIVE_HUNDRED = 500
    ONE_THOUSAND = 1000


class CrawlDepth(Enum):
    SHALLOW = 5
    AVERAGE = 8
    DEEP = 12


class ConcurrentRequestLimit(Enum):
    GENTLE = 10
    AVERAGE = 20
    AGGRESIVE = 30


difficulty_ranges = {
    Difficulty.EASY: range(50, 1000),
    Difficulty.MEDIUM: range(1000, 10000),
    Difficulty.HARD: range(10000, 100000),
}

compressor_extensions = {Compressor.GZIP.value: ".gz", Compressor.LZMA.value: ".xz"}

HTTP_SCHEME = "http://"
HTTPS_SCHEME = "https://"
