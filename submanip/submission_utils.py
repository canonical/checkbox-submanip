import json
import logging
import os
import tarfile
from tempfile import TemporaryDirectory, mkdtemp

from plainbox.impl.ctrl import gen_rfc822_records_from_io_log
from plainbox.impl.providers.special import get_exporters
from plainbox.impl.resource import Resource
from plainbox.impl.result import IOLogRecord
from plainbox.impl.result import MemoryJobResult
from plainbox.impl.session import SessionManager
from plainbox.impl.unit.category import CategoryUnit
from plainbox.impl.unit.job import JobDefinition
from plainbox.impl.result import outcome_meta
from plainbox.impl.session.system_information import (
    CollectorOutputs,
)

# Name-space prefix for Canonical Certification
CERTIFICATION_NS = "com.canonical.certification::"

logger = logging.getLogger(__name__)


class CheckboxSubmission:

    output_file = ""

    def __init__(self, submission, form_data):
        tmpdir = TemporaryDirectory()
        output_tmpdir = mkdtemp(prefix="submanip-")
        output_file = os.path.join(
            output_tmpdir, "submanip-" + os.path.basename(submission)
        )
        self.job_dict = {}
        self.category_dict = {}
        self.system_information = []
        self.description = ""
        self.testplan_id = ""
        self.custom_joblist = False
        self.rejected_jobs = []
        session_title = self._parse_submission(submission, tmpdir, form_data)
        manager = SessionManager.create_with_unit_list(
            list(self.job_dict.values()) + list(self.category_dict.values())
        )
        manager.state.metadata.title = session_title
        manager.state.metadata.custom_joblist = self.custom_joblist
        manager.state.metadata.rejected_jobs = [
            j["full_id"] for j in self.rejected_jobs
        ]
        blob = {"description": self.description, "testplan_id": self.testplan_id}
        self.update_app_blob(manager, json.dumps(blob).encode("UTF-8"))
        for job in self.job_dict.values():
            self._populate_session_state(job, manager.state)
        exporter = self._create_exporter("com.canonical.plainbox::tar")
        with open(output_file, "wb") as stream:
            exporter.dump_from_session_manager(manager, stream)
        with tarfile.open(output_file) as tar:
            tar.extractall(tmpdir.name)
        with tarfile.open(output_file, mode="w:xz") as tar:
            tar.add(tmpdir.name, arcname="")
        self.output_file = output_file

    def update_app_blob(self, manager, app_blob: bytes) -> None:
        """
        Update custom app data and save the session in the session storage.

        :param app_blob:
            Bytes sequence containing JSON-ised app_blob object.

        """
        if manager.state.metadata.app_blob == b"":
            updated_blob = app_blob
        else:
            current_dict = json.loads(manager.state.metadata.app_blob.decode("UTF-8"))
            current_dict.update(json.loads(app_blob.decode("UTF-8")))
            updated_blob = json.dumps(current_dict).encode("UTF-8")
        manager.state.metadata.app_blob = updated_blob
        manager.checkpoint()

    def _parse_submission(self, submission, tmpdir, form_data, mode="dict"):
        try:
            with tarfile.open(submission) as tar:
                tar.extractall(tmpdir.name)
                with open(os.path.join(tmpdir.name, "submission.json")) as f:
                    data = json.load(f)
            self.testplan_id = data.get("testplan_id", "")
            self.custom_joblist = data.get("custom_joblist", False)
            # import pdb; pdb.set_trace()
            self.rejected_jobs = data.get("rejected-jobs", [])
            title = form_data.get("session-title")
            if title:
                data["title"] = title
            description = form_data.get("session-description")
            # HTML textareas seem to return CRLF instead of Unix-style LF, cleaning this up
            self.description = description.replace("\r\n", "\n")
            for result in data["results"]:
                result["plugin"] = "shell"  # Required so default to shell
                result["summary"] = result["name"]
                # 'id' field in json file only contains partial id
                result["id"] = result.get("full_id", result["id"])
                if "::" not in result["id"]:
                    result["id"] = CERTIFICATION_NS + result["id"]
                # We update the content of the original submission with data
                # from the user-submitted HTML form
                comment = (
                    form_data.get(
                        result["full_id"] + "-comment", default=result["comments"]
                    )
                    or None
                )
                # import pdb; pdb.set_trace()
                outcome = form_data.get(
                    result["full_id"] + "-outcome", default=result["outcome"]
                )
                result["comments"] = comment
                result["status"] = outcome_meta(outcome).hexr_mapping
                result["outcome"] = outcome
                if mode == "list":
                    self.job_list.append(JobDefinition(result))
                elif mode == "dict":
                    self.job_dict[result["id"]] = JobDefinition(result)
            for result in data["resource-results"]:
                result["plugin"] = "resource"
                result["summary"] = result["name"]
                # 'id' field in json file only contains partial id
                result["id"] = result.get("full_id", result["id"])
                if "::" not in result["id"]:
                    result["id"] = CERTIFICATION_NS + result["id"]
                if mode == "list":
                    self.job_list.append(JobDefinition(result))
                elif mode == "dict":
                    self.job_dict[result["id"]] = JobDefinition(result)
            for result in data["attachment-results"]:
                result["plugin"] = "attachment"
                result["summary"] = result["name"]
                # 'id' field in json file only contains partial id
                result["id"] = result.get("full_id", result["id"])
                if "::" not in result["id"]:
                    result["id"] = CERTIFICATION_NS + result["id"]
                if mode == "list":
                    self.job_list.append(JobDefinition(result))
                elif mode == "dict":
                    self.job_dict[result["id"]] = JobDefinition(result)
            for cat_id, cat_name in data["category_map"].items():
                if mode == "list":
                    self.category_list.append(
                        CategoryUnit({"id": cat_id, "name": cat_name})
                    )
                elif mode == "dict":
                    self.category_dict[cat_id] = CategoryUnit(
                        {"id": cat_id, "name": cat_name}
                    )
            self.system_information = CollectorOutputs.from_dict(
                data["system_information"]
            )
        except OSError as e:
            raise SystemExit(e)
        except KeyError as e:
            raise SystemExit(e)
        return data["title"]

    def _populate_session_state(self, job, state):
        io_log = [
            IOLogRecord(count, "stdout", line.encode("utf-8"))
            for count, line in enumerate(
                job.get_record_value("io_log").splitlines(keepends=True)
            )
        ]
        result = MemoryJobResult(
            {
                "outcome": job.get_record_value(
                    "outcome", job.get_record_value("status")
                ),
                "comments": job.get_record_value("comments"),
                "execution_duration": job.get_record_value("duration"),
                "io_log": io_log,
            }
        )
        state.update_job_result(job, result)
        if job.plugin == "resource":
            new_resource_list = []
            for record in gen_rfc822_records_from_io_log(job, result):
                resource = Resource(record.data)
                new_resource_list.append(resource)
            if not new_resource_list:
                new_resource_list = [Resource({})]
            state.set_resource_list(job.id, new_resource_list)
        job_state = state.job_state_map[job.id]
        job_state.effective_category_id = job.get_record_value(
            "category_id", "com.canonical.plainbox::uncategorised"
        )
        job_state.effective_certification_status = job.get_record_value(
            "certification_status", "unspecified"
        )
        state.system_information = self.system_information

    def _create_exporter(self, exporter_id):
        exporter_map = {}
        exporter_units = get_exporters().unit_list
        for unit in exporter_units:
            if unit.Meta.name == "exporter":
                support = unit.support
                if support:
                    exporter_map[unit.id] = support
        exporter_support = exporter_map[exporter_id]
        return exporter_support.exporter_cls([], exporter_unit=exporter_support)
