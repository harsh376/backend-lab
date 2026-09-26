import re
from dataclasses import dataclass
from typing import Literal

type CellID = str
type TermType = Literal["int", "cell"]


@dataclass(frozen=True)
class Term:
    type_: TermType
    value: str
    sign: Literal[-1, 1]


@dataclass(frozen=True)
class Cell:
    id_: CellID
    terms: tuple[Term, ...]  # Tuple is immutable compared to list


class CellNotFoundException(Exception):
    pass


class CycleFoundException(Exception):
    pass


class SpreadsheetService:
    def __init__(self):
        self.cells: dict[CellID, Cell] = {}

    def _tokenize(self, expr: str) -> list[tuple[str, str]]:
        return [
            (sign or "+", value)
            for sign, value in re.findall(r"([+-]?)([^+\-\s]+)", expr.replace(" ", ""))
        ]

    def _is_integer(self, value: str) -> bool:
        try:
            int(value)
            return True
        except ValueError:
            return False

    def _get_terms(self, value: str) -> tuple[Term, ...]:
        tokens = self._tokenize(value)
        terms = []
        for sign, token_value in tokens:
            if self._is_integer(token_value):
                terms.append(
                    Term(
                        type_="int",
                        value=token_value,
                        sign=1 if sign == "+" else -1,
                    )
                )
            else:
                if token_value not in self.cells:
                    raise CellNotFoundException(f"{token_value} DNE")
                terms.append(
                    Term(
                        type_="cell",
                        value=token_value,
                        sign=1 if sign == "+" else -1,
                    )
                )
        return tuple(terms)

    def _evaluate(self, cell: Cell) -> int:
        cache = {}
        visited = {cell.id_}

        def dfs(cell: Cell):
            # Recurse/Gather
            term_values = []
            for term in cell.terms:
                if term.type_ == "int":
                    term_values.append(term.sign * int(term.value))
                else:
                    dep_cell_id = term.value
                    if dep_cell_id in cache:
                        term_values.append(cache[dep_cell_id])
                        continue

                    if dep_cell_id in visited:
                        raise CycleFoundException(
                            f"Cycle found in expression: {dep_cell_id}"
                        )

                    dep_cell = self.cells[dep_cell_id]
                    visited.add(dep_cell.id_)
                    computed_value = dfs(dep_cell)
                    term_values.append(computed_value)

            # Combine
            result = sum(term_values)

            # Update global
            cache[cell.id_] = result

            # Return to parent
            return result

        return dfs(cell)

    def _evaluate_iterative(self, cell: Cell) -> int:
        cache = {}
        visited = {cell.id_}
        # Suspended outer contexts: (cell, index of next term, running total,
        # sign of pending term)
        stack = []
        current, i, total = cell, 0, 0

        while True:
            if i < len(current.terms):
                term = current.terms[i]
                i += 1
                if term.type_ == "int":
                    total += term.sign * int(term.value)
                elif term.value in cache:
                    total += term.sign * cache[term.value]
                elif term.value in visited:
                    raise CycleFoundException(
                        f"Cycle found in expression: {term.value}"
                    )
                else:
                    # Suspend: save the outer context and start evaluating the
                    # dependency
                    visited.add(term.value)
                    stack.append((current, i, total, term.sign))
                    current, i, total = self.cells[term.value], 0, 0
            else:
                # Finish the inner context
                cache[current.id_] = total
                if not stack:
                    return total

                # Resume: restore the outer context and combine the inner result
                inner_result = total
                current, i, total, sign = stack.pop()
                total += sign * inner_result

    def set_cell(self, cell_id: CellID, value: str) -> CellID:
        terms = self._get_terms(value)
        cell = Cell(
            id_=cell_id,
            terms=terms,
        )
        # Evaluate to detect cycles
        self._evaluate_iterative(cell)
        self.cells[cell_id] = cell
        return cell_id

    def get_cell(self, cell_id: CellID) -> int:
        cell = self.cells.get(cell_id)
        if cell is None:
            raise CellNotFoundException
        return self._evaluate_iterative(cell)
