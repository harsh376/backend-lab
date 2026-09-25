import re


class Spreadsheet:
    CELL = re.compile(r"[A-Z]+[0-9]+")
    INTEGER = re.compile(r"-?[0-9]+")

    def __init__(self):
        self.cells: dict[str, list[int | tuple[str, int]]] = {}
        self.dependencies: dict[str, set[str]] = {}

    def _validate_cell(self, name: str) -> None:
        if not self.CELL.fullmatch(name):
            raise ValueError(f"Invalid cell name: {name}")

    def _parse(self, value: int | str) -> list[int | tuple[str, int]]:
        if isinstance(value, int):
            return [value]

        terms = []

        tokens = [t for t in re.split(r"(?=[+-])", value.replace(" ", "")) if t]
        if not tokens:
            raise ValueError(f"Invalid formula term: {value!r}")

        for raw_term in tokens:
            sign = -1 if raw_term.startswith("-") else 1
            term = raw_term.lstrip("+-")

            if self.INTEGER.fullmatch(term):
                terms.append(sign * int(term))
            elif self.CELL.fullmatch(term):
                terms.append((term, sign))
            else:
                raise ValueError(f"Invalid formula term: {raw_term!r}")

        return terms

    def set_cell(self, name: str, value: int | str) -> bool:
        self._validate_cell(name)
        terms = self._parse(value)
        new_dependencies = {term[0] for term in terms if isinstance(term, tuple)}

        # Adding name -> dependency creates a cycle exactly when
        # that dependency can already reach name.
        stack = list(new_dependencies)
        visited = set()

        while stack:
            current = stack.pop()

            if current == name:
                return False

            if current in visited:
                continue

            visited.add(current)
            stack.extend(self.dependencies.get(current, ()))

        # Commit only after cycle validation.
        self.cells[name] = terms
        self.dependencies[name] = new_dependencies
        return True

    def get_cell(self, name: str) -> int:
        self._validate_cell(name)
        memo = {}

        def evaluate(cell: str) -> int:
            if cell in memo:
                return memo[cell]

            total = 0
            for term in self.cells.get(cell, ()):
                if isinstance(term, int):
                    total += term
                else:
                    ref, sign = term
                    total += sign * evaluate(ref)

            memo[cell] = total
            return total

        return evaluate(name)
