#!/usr/bin/env python3

import logging
import os
import tomllib
from argparse import ArgumentParser
from enum import StrEnum
from pathlib import Path

import uvicorn
import uvicorn.config

logger = logging.getLogger("Uvicorn.Server")


class Environment(StrEnum):
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--profile",
        type=Environment,
        default=Environment.DEVELOPMENT,
        help="The configuration profile to be loaded",
    )
    args = parser.parse_args()

    config = tomllib.loads(
        Path.cwd().joinpath("run.config.toml").read_text(encoding="utf-8")
    )

    for k, v in config["config"][args.profile.value].items():
        if isinstance(v, int):
            continue
        os.environ[k] = v

    try:
        uvicorn.run(
            "src.main:app",
            host=config["config"]["host"],
            port=config["config"]["port"],
            log_level="info",
            reload=True if args.profile == Environment.DEVELOPMENT else False,
            workers=config["config"][args.profile.value]["worker_threads"]
            if args.profile == Environment.PRODUCTION
            else None,
            timeout_keep_alive=config["config"][args.profile.value]["timeout"],
        )
    except Exception as e:
        logger.error("Uvicorn failed to start")
        logger.error(e)
    finally:
        exit(0)
