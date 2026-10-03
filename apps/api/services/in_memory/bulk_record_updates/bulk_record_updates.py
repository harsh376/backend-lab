from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal


class ServiceError(Exception):
    pass


class DoesNotExist(ServiceError):
    pass


class AlreadyExists(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


type RecordID = str
type RecordStatus = Literal["draft", "published", "archived"]
type BatchMode = Literal["partial", "atomic"]
type OutcomeCategory = Literal["updated", "unchanged", "failed", "blocked"]


@dataclass(frozen=True)
class Record:
    id_: RecordID
    title: str
    status: RecordStatus
    version: int = 1


@dataclass(frozen=True)
class RecordChange:
    record_id: RecordID
    version: int
    before: Record
    after: Record


@dataclass(frozen=True)
class Outcome:
    record_id: RecordID
    category: OutcomeCategory
    errors: list[str]
    previous: RecordStatus | None = None
    current: RecordStatus | None = None


@dataclass(frozen=True)
class BatchSummary:
    outcomes: list[Outcome]
    target_status: RecordStatus
    mode: BatchMode
    total: int  # total = updated + unchanged + failed + blocked
    updated: int
    unchanged: int
    failed: int
    blocked: int


class BulkRecordUpdateService:
    def __init__(self):

        self.records: dict[RecordID, Record] = {}
        self.record_history: dict[RecordID, list[RecordChange]] = defaultdict(list)

    def _validate_non_empty_string(self, value: str):
        if not isinstance(value, str) or value.isspace() or value == "":
            raise ValidationError("Not a string")

    def _validate_record_id(self, value: str):
        self._validate_non_empty_string(value)

    def _validate_status(self, value: str):
        self._validate_non_empty_string(value)
        if value not in ["draft", "published", "archived"]:
            raise ValidationError("Bad option")

    def _validate_batch_mode(self, value: str):
        self._validate_non_empty_string(value)
        if value not in ["partial", "atomic"]:
            raise ValidationError("Bad option")

    def create_record(
        self,
        record_id: RecordID,
        title: str,
        status: RecordStatus = "draft",
    ) -> RecordID:
        self._validate_non_empty_string(record_id)
        self._validate_non_empty_string(title)
        self._validate_status(status)

        if record_id in self.records:
            raise AlreadyExists("record already exists")

        self.records[record_id] = Record(
            id_=record_id,
            title=title,
            status=status,
        )
        return record_id

    def inspect_record(self, record_id: RecordID) -> Record:
        self._validate_non_empty_string(record_id)

        record = self.records.get(record_id)
        if record is None:
            raise DoesNotExist("Record does not exist")

        return record

    def _validate(
        self,
        record_id: RecordID,
        target_status: RecordStatus,
    ) -> Outcome:
        valid_transitions = {
            "draft": {"draft", "published", "archived"},
            "published": {"published", "archived"},
            "archived": {"archived"},
        }

        if record_id not in self.records:
            return Outcome(
                record_id=record_id, category="failed", errors=["Record does not exist"]
            )

        record = self.records[record_id]
        if target_status not in valid_transitions[record.status]:
            return Outcome(
                record_id=record_id,
                previous=record.status,
                current=record.status,
                category="failed",
                errors=["Bad state transition"],
            )

        return Outcome(
            record_id=record_id,
            previous=record.status,
            current=target_status,
            category="updated" if record.status != target_status else "unchanged",
            errors=[],
        )

    def bulk_update_statuses(
        self,
        record_ids: list[RecordID],
        target_status: RecordStatus,
        mode: BatchMode = "partial",
    ) -> BatchSummary:
        self._validate_status(target_status)
        self._validate_batch_mode(mode)
        for record_id in record_ids:
            self._validate_record_id(record_id)

        # Generate outcomes for each row
        outcomes: list[Outcome] = [
            self._validate(record_id, target_status) for record_id in record_ids
        ]

        # Keep the first outcome for each ID in selection order.
        new_outcomes = []
        seen: set[RecordID] = set()
        for o in outcomes:
            if o.record_id in seen:
                continue
            new_outcomes.append(o)
            seen.add(o.record_id)
        outcomes = new_outcomes

        # Check if batch has error
        batch_has_error = any(o.category == "failed" for o in outcomes)

        # If batch has error, update outcomes as needed
        if mode == "atomic":
            outcomes = [
                replace(
                    o,
                    category="blocked",
                    current=o.previous,
                    errors=[
                        "Change blocked because another record in the batch failed"
                    ],
                )
                if (o.category == "updated" and batch_has_error)
                else o
                for o in outcomes
            ]

        # Process outcomes
        for outcome in outcomes:
            if mode == "atomic" and batch_has_error:
                continue

            if outcome.category == "updated":
                after = replace(
                    self.records[outcome.record_id],
                    status=target_status,
                    version=self.records[outcome.record_id].version + 1,
                )
                record_change = RecordChange(
                    version=after.version,
                    record_id=outcome.record_id,
                    before=self.records[outcome.record_id],
                    after=after,
                )
                self.record_history[outcome.record_id].append(record_change)
                self.records[outcome.record_id] = after

        return BatchSummary(
            outcomes=outcomes,
            target_status=target_status,
            mode=mode,
            total=len(outcomes),
            updated=sum(1 for o in outcomes if o.category == "updated"),
            unchanged=sum(1 for o in outcomes if o.category == "unchanged"),
            failed=sum(1 for o in outcomes if o.category == "failed"),
            blocked=sum(1 for o in outcomes if o.category == "blocked"),
        )

    def get_record(self, record_id: RecordID) -> Record:
        self._validate_record_id(record_id)

        record = self.records.get(record_id)
        if record is None:
            raise DoesNotExist

        return record

    def update_record(
        self, record_id: RecordID, patch: dict, expected_version: int
    ) -> bool:
        self._validate_record_id(record_id)
        if type(expected_version) is not int or expected_version <= 0:
            raise ValidationError("expected_version is not positive")

        record = self.records.get(record_id)
        if record is None:
            raise DoesNotExist

        if expected_version != record.version:
            raise ValidationError("version mismatch")

        needs_update = False
        after = record

        for field in patch:
            if field == "title":
                new_title = patch[field]
                self._validate_non_empty_string(new_title)
                if new_title != record.title:
                    after = replace(after, title=new_title)
                    needs_update = True

            elif field == "status":
                new_status = patch["status"]
                self._validate_status(new_status)
                outcome = self._validate(record_id, new_status)
                if outcome.errors:
                    raise ValidationError("Invalid status")
                if new_status != record.status:
                    after = replace(after, status=new_status)
                    needs_update = True

        if needs_update:
            after = replace(after, version=expected_version + 1)
            record_change = RecordChange(
                version=after.version,
                record_id=record_id,
                before=record,
                after=after,
            )
            self.record_history[record_id].append(record_change)
            self.records[record_id] = after
            return True
        return False

    def get_record_history(self, record_id: RecordID) -> list[RecordChange]:
        self._validate_record_id(record_id)

        record = self.records.get(record_id)
        if record is None:
            raise DoesNotExist

        record_history = self.record_history[record_id]
        return deepcopy(record_history)
