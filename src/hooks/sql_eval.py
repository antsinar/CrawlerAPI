from __future__ import annotations

import sys
from functools import cached_property
from pathlib import Path

try:
    sys.path.append(Path(__file__).parent.parent.parent.as_posix())
except Exception as e:
    print(e)
    exit(1)

import logging
from importlib.util import find_spec, module_from_spec
from typing import Dict, List

import tree_sitter_python as tspython
from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase
from tree_sitter import Language, Parser


class SchemaMapper:
    """
    A class for mapping python files inside the codebase to SQLAlchemy models
    """

    def __init__(self, root_dir: Path):
        """
        Constructor method

        Args:
            root_dir (Path): Where to start looking for python files

        """
        self.root_dir = root_dir
        sys.path.append(self.root_dir.as_posix())
        self.parser = Parser(language=Language(tspython.language()))
        self.exclude_dirs = ["alembic", "hooks", "migrations"]
        self.spec = None
        self.base_class = self.find_base_class()
        self.table_map: Dict[Path, List[type]] = dict()

    @cached_property
    def python_files(self) -> List[Path]:
        """
        Search root dir recursively and return all the python files not in exclude_dirs

        Returns:
            List[Path]: List of python files, as path objects
        """
        return [
            file
            for file in self.root_dir.rglob("*.py")
            if file.name.endswith(".py") and file.parent.name not in self.exclude_dirs
        ]

    def find_base_import(self) -> None:
        """
        Find the first python file that imports DeclarativeBase
        """
        for file in self.python_files:
            tree = self.parser.parse(file.read_bytes())
            declarative_imported = [
                node.text
                for node in tree.root_node.children
                if node.type == "import_from_statement"
                and b"DeclarativeBase" in node.text
            ]

            if not declarative_imported:
                continue
            rel = (
                file.relative_to(self.root_dir)
                .as_posix()
                .replace(".py", "")
                .replace("/", ".")
            )
            self.spec = find_spec(rel)
            return

    def find_base_class(self) -> DeclarativeBase:
        """
        Find the sqlalchemy class that inherits from DeclarativeBase

        Raises:
            Exception: If no class is found

        Returns:
            DeclarativeBase: The inherited instance of DeclarativeBase
        """
        self.find_base_import()
        try:
            module = module_from_spec(self.spec)
            sys.modules[self.spec.name] = module
            self.spec.loader.exec_module(module)

            base_class = [
                getattr(module, item)
                for item in dir(module)
                if not item.startswith("_")
                and isinstance(getattr(module, item), type)
                and getattr(module, item) in DeclarativeBase.__subclasses__()
            ]

            return base_class[0]

        except Exception as e:
            raise Exception(f"Could not load module: {e}")

    def map_tables(self):
        """
        Map file paths to sqlalchemy tables for quick access
        """
        for sb in self.base_class.__subclasses__():
            key = self.table_map.get(
                (self.root_dir / f"{sb.__module__.replace('.', '/')}.py"), None
            )
            if not key:
                self.table_map[
                    self.root_dir / f"{sb.__module__.replace('.', '/')}.py"
                ] = list()
            self.table_map[
                self.root_dir / f"{sb.__module__.replace('.', '/')}.py"
            ].append(sb)


class QueryFinder:
    """
    Parse python files and extract sqlalchemy core queries
    """

    def __init__(self, root_dir: Path, table_dirs: List[Path]) -> None:
        self.root_dir = root_dir
        self.table_dirs = table_dirs
        self.parser = Parser(language=Language(tspython.language()))
        self.exclude_dirs = ["alembic", "hooks", "migrations", "versions"]
        self.query_types = ["select", "insert", "update", "delete", "text"]
        self.queries: List[str] = []

    @cached_property
    def python_files(self) -> List[Path]:
        """
        Search root dir recursively and return all the python files not in exclude_dirs and table_dirs

        Returns:
            List[Path]: List of python files, as path objects
        """
        return [
            file
            for file in self.root_dir.rglob("*.py")
            if file.name.endswith(".py")
            and file.parent.name not in [*self.exclude_dirs, *self.table_dirs]
        ]

    def find_query_nodes(self):
        """
        Return all node objects that contain one of the query types in their contents
        """
        nodes = list()
        for file in self.python_files:
            tree = self.parser.parse(file.read_bytes())
            nodes.extend(
                [
                    node
                    for node in tree.root_node.children
                    if node.type == "class_definition"
                    and any(
                        [
                            q in node.text
                            for q in map(lambda x: x.encode("utf-8"), self.query_types)
                        ]
                    )
                ]
            )
        return nodes

    def find_queries(self):
        raise NotImplementedError


class QueryCompiler:
    """
    Compile sqlalchemy core expressions into raw SQL with the correct dialect
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine


class QueryTester: ...


class CLIReport: ...


class Cache: ...


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    root_dir = Path(__file__).parent.parent
    mapper = SchemaMapper(root_dir)
    mapper.map_tables()
    queries = QueryFinder(
        root_dir,
        [
            file_name.parent.relative_to(root_dir).as_posix().split(".")[-1]
            for file_name in mapper.table_map.keys()
        ],
    ).find_queries()
