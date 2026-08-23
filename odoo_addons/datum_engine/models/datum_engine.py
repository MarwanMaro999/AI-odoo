"""Odoo system of record for Datum Engine workflows."""

import base64
import json
from urllib.parse import urlparse
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


RUN_STATES = [(x, x.replace("_", " ").title()) for x in ("queued", "running", "succeeded", "failed", "cancelled")]
DOCUMENT_STATES = [(x, x.replace("_", " ").title()) for x in ("drafting", "in_review", "findings_open", "awaiting_clarification", "escalated", "cleared", "abandoned")]
FINDING_STATES = [(x, x.title()) for x in ("open", "resolved", "waived", "superseded", "regressed")]


class DatumEngagement(models.Model):
    _name = "datum.engagement"
    _description = "Datum Engagement"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    prospect_context = fields.Text(string="What do we already know?", help="Paste the prospect context, notes, or email summary here.")
    meeting_transcript = fields.Text(string="Meeting transcript", help="Paste the transcript or meeting notes here after the discovery meeting.")
    workflow_status = fields.Char(compute="_compute_workflow_status", string="Current status")
    source_artifact_ids = fields.One2many("datum.source.artifact", "engagement_id")
    document_ids = fields.One2many("datum.document", "engagement_id")
    document_version_ids = fields.Many2many(
        "datum.document.version",
        compute="_compute_document_version_ids",
        string="Generated files",
    )
    run_ids = fields.One2many("datum.run", "engagement_id")
    cycle_ids = fields.One2many("datum.review.cycle", "engagement_id")

    @api.depends("document_ids.version_ids")
    def _compute_document_version_ids(self):
        for record in self:
            record.document_version_ids = record.document_ids.mapped("version_ids")

    @api.depends("run_ids.state", "run_ids.skill_identifier", "run_ids.create_date")
    def _compute_workflow_status(self):
        for record in self:
            latest = record.run_ids.sorted("create_date", reverse=True)[:1]
            record.workflow_status = (
                f"{latest.skill_identifier.replace('-', ' ').title()}: {latest.state.title()}"
                if latest
                else "Add information, then choose what to create."
            )

    def _upsert_source(self, source_type, source_key, content, name):
        self.ensure_one()
        if not content or not content.strip():
            raise UserError(_("Please enter %s first.") % name.lower())
        current = self.source_artifact_ids.filtered(
            lambda source: source.source_key == source_key and source.is_current
        )
        if current and current.content == content:
            return current
        next_revision = max(
            self.source_artifact_ids.filtered(lambda source: source.source_key == source_key).mapped("revision") or [0]
        ) + 1
        current.write({"is_current": False})
        return self.env["datum.source.artifact"].create({
            "name": name,
            "engagement_id": self.id,
            "source_key": source_key,
            "revision": next_revision,
            "source_type": source_type,
            "content": content.strip(),
        })

    def _start_simple_run(self, skill_identifier, parameters=None):
        self.ensure_one()
        current_sources = self.source_artifact_ids.filtered("is_current")
        source_revision = str(max(current_sources.mapped("revision") or [1]))
        run = self.env["datum.run"].create({
            "engagement_id": self.id,
            "skill_identifier": skill_identifier,
            "source_set_revision": source_revision,
            "parameters_json": json.dumps(parameters or {}),
        })
        run.action_submit()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Work started"),
                "message": _("Your document is being created. Its status and file will appear here automatically."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_create_discovery_questions(self):
        self.ensure_one()
        self._upsert_source("prospect_context", "prospect-context", self.prospect_context, _("Prospect context"))
        return self._start_simple_run("gen-discovery-questions")

    def action_create_strs(self):
        self.ensure_one()
        self._upsert_source("prospect_context", "prospect-context", self.prospect_context, _("Prospect context"))
        self._upsert_source("meeting_transcript", "meeting-transcript", self.meeting_transcript, _("Meeting transcript"))
        return self._start_simple_run("gen-strs")

    def action_start_transcript_workflow(self):
        """Generate StRS first; an approved StRS is required before the SOW."""
        self.ensure_one()
        self._upsert_source("prospect_context", "prospect-context", self.prospect_context, _("Prospect context"))
        self._upsert_source("meeting_transcript", "meeting-transcript", self.meeting_transcript, _("Meeting transcript"))
        return self._start_simple_run("gen-strs")

    def action_create_scope_of_work(self):
        self.ensure_one()
        self._prepare_approved_strs_source()
        return self._start_simple_run("gen-sow")

    def _prepare_approved_strs_source(self):
        """Register the approved client StRS as the only mandatory SOW baseline."""
        self.ensure_one()
        approved_strs = self.document_ids.filtered(
            lambda document: document.document_type == "strs"
        ).mapped("version_ids").filtered(
            lambda version: version.distribution_class == "client_permitted" and version.state == "cleared"
        ).sorted("version_number", reverse=True)[:1]
        if not approved_strs:
            raise UserError(_("Approve the client StRS version before creating the Scope of Work."))
        if not approved_strs.generated_source_text:
            raise UserError(_("The approved StRS has no usable generated content. Regenerate the StRS first."))
        self._upsert_source(
            "approved_requirements_specification",
            "approved-strs",
            approved_strs.generated_source_text,
            _("Approved StRS"),
        )

    def _regenerate_document(self, document_type, instructions, previous_version):
        """Create a new generated version from a specific document and edit request."""
        self.ensure_one()
        parameters = {
            "regeneration": True,
            "revision_instructions": instructions.strip(),
            "previous_document_version": previous_version.name,
        }
        if document_type == "discovery_questionnaire":
            self._upsert_source("prospect_context", "prospect-context", self.prospect_context, _("Prospect context"))
            return self._start_simple_run("gen-discovery-questions", parameters)
        if document_type == "strs":
            self._upsert_source("prospect_context", "prospect-context", self.prospect_context, _("Prospect context"))
            self._upsert_source("meeting_transcript", "meeting-transcript", self.meeting_transcript, _("Meeting transcript"))
            return self._start_simple_run("gen-strs", parameters)
        if document_type == "scope_of_work":
            self._prepare_approved_strs_source()
            return self._start_simple_run("gen-sow", parameters)
        raise UserError(_("This document type cannot be regenerated."))

    def action_review_scope_of_work(self):
        self.ensure_one()
        self._upsert_source("meeting_transcript", "meeting-transcript", self.meeting_transcript, _("Meeting transcript"))
        scope_document = self.document_ids.filtered(lambda document: document.document_type == "scope_of_work")
        latest_version = scope_document.version_ids.sorted("version_number", reverse=True)[:1]
        if not latest_version:
            raise UserError(_("Create the Scope of Work before reviewing it."))
        if not latest_version.generated_source_text:
            raise UserError(_("The Scope of Work has no usable generated content. Regenerate it before reviewing."))
        self._upsert_source(
            "sow_version",
            f"sow-version-{latest_version.version_number}",
            latest_version.generated_source_text,
            latest_version.name,
        )
        return self._start_simple_run("rev-sow", {"target_document_version": latest_version.name})

    def action_fix_and_regenerate_scope(self):
        self.ensure_one()
        open_findings = self.env["datum.finding"].search([
            ("engagement_id", "=", self.id),
            ("state", "in", ["open", "regressed"]),
            ("resolution_route", "=", "regenerate"),
        ])
        directed_findings = [{
            "finding_key": finding.finding_key,
            "severity": finding.severity,
            "category": finding.category,
            "location": finding.location,
            "summary": finding.summary,
            "resolution_route": finding.resolution_route,
        } for finding in open_findings]
        self._upsert_source("meeting_transcript", "meeting-transcript", self.meeting_transcript, _("Meeting transcript"))
        return self._start_simple_run("gen-sow", {"directed_findings": directed_findings})

    def action_refresh_ai_status(self):
        """Called by the project screen while a run is active; it avoids a manual refresh."""
        updates = []
        for record in self:
            for run in record.run_ids.filtered(
                lambda item: item.state in ("queued", "running") and item.external_run_id
            ):
                previous_state = run.state
                run._poll_engine_status()
                if previous_state != run.state:
                    updates.append({
                        "run_name": run.name,
                        "skill": run.skill_identifier,
                        "state": run.state,
                        "failure_code": run.failure_code,
                    })
        return updates


class DatumSourceArtifact(models.Model):
    _name = "datum.source.artifact"
    _description = "Immutable Datum Source Artefact"
    _order = "source_key, revision desc"

    name = fields.Char(required=True)
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    source_key = fields.Char(required=True, help="Stable identity across revisions.")
    revision = fields.Integer(default=1, required=True)
    source_type = fields.Selection([("prospect_context", "Prospect Context"), ("meeting_transcript", "Meeting Transcript"), ("approved_requirements_specification", "Approved StRS"), ("sow_version", "Scope of Work Version"), ("attachment", "Attachment"), ("clarification_answers", "Clarification Answers")], required=True)
    content = fields.Text(required=True)
    attachment_id = fields.Many2one("ir.attachment", ondelete="restrict")
    superseded_by_id = fields.Many2one("datum.source.artifact", readonly=True)
    is_current = fields.Boolean(default=True)
    created_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)

    _sql_constraints = [("datum_source_revision_unique", "unique(engagement_id, source_key, revision)", "A source revision must be unique within its engagement.")]

    def action_new_revision(self):
        self.ensure_one()
        self.is_current = False
        revision = self.copy({"revision": self.revision + 1, "is_current": True, "superseded_by_id": False})
        self.superseded_by_id = revision
        self.engagement_id.document_ids.mapped("version_ids").filtered(lambda version: version.state != "abandoned").write({"is_stale": True})
        return {"type": "ir.actions.act_window", "res_model": "datum.source.artifact", "res_id": revision.id, "view_mode": "form"}


class DatumDocument(models.Model):
    _name = "datum.document"
    _description = "Datum Document"
    _sql_constraints = [("datum_document_unique", "unique(engagement_id, document_type)", "One document type is allowed per engagement.")]

    name = fields.Char(compute="_compute_name", store=True)
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    document_type = fields.Selection([("discovery_questionnaire", "Discovery Questionnaire"), ("strs", "StRS"), ("scope_of_work", "Scope of Work")], required=True)
    version_ids = fields.One2many("datum.document.version", "document_id")

    @api.depends("engagement_id.name", "document_type")
    def _compute_name(self):
        for record in self:
            record.name = f"{record.engagement_id.name or ''} - {record.document_type or ''}"


class DatumDocumentVersion(models.Model):
    _name = "datum.document.version"
    _description = "Datum Document Version"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "version_number desc"

    name = fields.Char(compute="_compute_name", store=True)
    document_id = fields.Many2one("datum.document", required=True, ondelete="cascade")
    document_type = fields.Selection(related="document_id.document_type", store=True, readonly=True)
    engagement_id = fields.Many2one(related="document_id.engagement_id", store=True)
    version_number = fields.Integer(required=True, default=1)
    state = fields.Selection(DOCUMENT_STATES, default="drafting", tracking=True, required=True)
    distribution_class = fields.Selection([("client_permitted", "Client Permitted"), ("internal_only", "Internal Only")], required=True)
    attachment_id = fields.Many2one("ir.attachment", ondelete="restrict")
    preview_url = fields.Char(readonly=True)
    preview_attachment_id = fields.Many2one("ir.attachment", ondelete="restrict", readonly=True)
    generated_source_text = fields.Text(readonly=True)
    source_set_revision = fields.Char(required=True)
    targeted_finding_ids = fields.Many2many("datum.finding", "datum_version_target_finding_rel", "version_id", "finding_id")
    is_stale = fields.Boolean(default=False, tracking=True)
    manually_edited = fields.Boolean(default=False)
    approved_by_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    run_id = fields.Many2one("datum.run", readonly=True)
    run_state = fields.Selection(related="run_id.state", string="Generation status")
    failure_code = fields.Char(related="run_id.failure_code", string="Failure reason")

    _sql_constraints = [("datum_version_unique", "unique(document_id, version_number, distribution_class)", "Version number and distribution class must be unique.")]

    @api.depends("document_id.name", "version_number", "distribution_class")
    def _compute_name(self):
        for record in self:
            record.name = f"{record.document_id.name or ''} v{record.version_number} ({record.distribution_class or ''})"

    def action_submit_for_review(self):
        self.write({"state": "in_review"})

    def action_clear(self):
        for record in self:
            if record.distribution_class != "client_permitted":
                raise UserError(_("Only a client-permitted version can be approved."))
            if record.is_stale:
                raise UserError(_("A stale version cannot be cleared."))
            record.write({"state": "cleared", "approved_by_id": self.env.user.id, "approved_at": fields.Datetime.now()})

    def action_open_regeneration_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Edit and regenerate"),
            "res_model": "datum.regenerate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_document_version_id": self.id},
        }

    def action_download_document(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("This file is not available yet."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "new",
        }

    def action_preview_document(self):
        self.ensure_one()
        if self.preview_attachment_id:
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{self.preview_attachment_id.id}",
                "target": "new",
            }
        if not self.preview_url:
            raise UserError(_("The browser preview is not available yet."))
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "datum_engine.service_url", "http://127.0.0.1:5000"
        )
        return {
            "type": "ir.actions.act_url",
            "url": base_url.rstrip("/") + self.preview_url,
            "target": "new",
        }


class DatumRun(models.Model):
    _name = "datum.run"
    _description = "Datum AI Run"
    _order = "create_date desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True)
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    skill_identifier = fields.Selection([("gen-discovery-questions", "Generate discovery questionnaire"), ("gen-strs", "Generate StRS"), ("gen-sow", "Generate Scope of Work"), ("rev-sow", "Review Scope of Work")], required=True)
    skill_version = fields.Char(default="1.0.0", required=True)
    state = fields.Selection(RUN_STATES, default="queued", readonly=True)
    external_run_id = fields.Char(readonly=True, index=True)
    source_set_revision = fields.Char(default="1", required=True)
    parameters_json = fields.Text(default="{}")
    output_ids = fields.One2many("datum.run.output", "run_id")
    finding_ids = fields.One2many("datum.finding", "run_id")
    verdict = fields.Selection([("cleared", "Cleared"), ("not_cleared", "Not Cleared")], readonly=True)
    failure_code = fields.Char(readonly=True)
    log_json = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = self.env["ir.sequence"].next_by_code("datum.run") or _("New")
        return super().create(values_list)

    def action_submit(self):
        for record in self:
            record._submit_to_engine()

    def action_open_regeneration_wizard(self):
        self.ensure_one()
        version = self.engagement_id.document_version_ids.filtered(
            lambda item: item.run_id == self
        ).sorted("version_number", reverse=True)[:1]
        if not version and self.skill_identifier == "rev-sow":
            version = self.engagement_id.document_version_ids.filtered(
                lambda item: item.document_type == "scope_of_work"
            ).sorted("version_number", reverse=True)[:1]
        if not version:
            raise UserError(_("This run has no document version that can be regenerated."))
        return version.action_open_regeneration_wizard()

    def _submit_to_engine(self):
        self.ensure_one()
        sources = self.engagement_id.source_artifact_ids.filtered("is_current")
        if not sources:
            raise UserError(_("Register at least one current source artefact before starting a run."))
        payload = {"idempotency_key": f"odoo-{self.id}", "engagement_id": str(self.engagement_id.id), "source_set_revision": self.source_set_revision, "skill": {"identifier": self.skill_identifier, "version": self.skill_version}, "source_material": [{"source_id": source.source_key, "revision": str(source.revision), "type": source.source_type, "name": source.name, "text": source.content} for source in sources], "parameters": json.loads(self.parameters_json or "{}")}
        try:
            response = self._engine_request("POST", "/api/v1/runs", payload)
        except URLError as error:
            raise UserError(_("Datum AI service is unavailable: %s") % error.reason) from error
        self.write({"external_run_id": response["run_id"], "state": response["state"], "log_json": json.dumps(response.get("log", []))})

    def _engine_request(self, method, path, payload=None):
        base_url = self.env["ir.config_parameter"].sudo().get_param("datum_engine.service_url", "http://127.0.0.1:5000")
        headers = {"Content-Type": "application/json"}
        token = self.env["ir.config_parameter"].sudo().get_param("datum_engine.api_auth_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base_url.rstrip("/") + path, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers=headers, method=method)
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    @api.model
    def cron_poll_ai_runs(self):
        for record in self.search([( "state", "in", ["queued", "running"]), ("external_run_id", "!=", False)]):
            record._poll_engine_status()

    def _poll_engine_status(self):
        """Synchronise one active engine run and import its completed files once."""
        self.ensure_one()
        try:
            status = self._engine_request("GET", f"/api/v1/runs/{self.external_run_id}")
        except URLError:
            return False
        was_succeeded = self.state == "succeeded"
        self.write({"state": status["state"], "verdict": status.get("verdict"), "failure_code": status.get("failure_code"), "log_json": json.dumps(status.get("log", []))})
        if status["state"] == "succeeded":
            self._import_status(status)
            if not was_succeeded:
                self._advance_automatic_flow()
        return True

    def _advance_automatic_flow(self):
        """Continue the transcript workflow only after its predecessor is complete."""
        self.ensure_one()
        parameters = json.loads(self.parameters_json or "{}")
        if not parameters.get("automatic_flow"):
            return

        cycle_number = int(parameters.get("cycle_number", 1))
        if self.skill_identifier == "gen-strs":
            self._start_follow_up("gen-sow", {"automatic_flow": True, "cycle_number": cycle_number})
            return

        if self.skill_identifier == "gen-sow":
            scope_document = self.env["datum.document"].search([
                ("engagement_id", "=", self.engagement_id.id),
                ("document_type", "=", "scope_of_work"),
            ], limit=1)
            latest_scope = scope_document.version_ids.sorted("version_number", reverse=True)[:1]
            if latest_scope:
                self._start_follow_up("rev-sow", {
                    "automatic_flow": True,
                    "cycle_number": cycle_number,
                    "target_document_version": latest_scope.name,
                })
            return

        if self.skill_identifier != "rev-sow":
            return

        scope_document = self.env["datum.document"].search([
            ("engagement_id", "=", self.engagement_id.id),
            ("document_type", "=", "scope_of_work"),
        ], limit=1)
        cycle = self.env["datum.review.cycle"].search([
            ("engagement_id", "=", self.engagement_id.id),
            ("document_id", "=", scope_document.id),
        ], limit=1) or self.env["datum.review.cycle"].create({
            "engagement_id": self.engagement_id.id,
            "document_id": scope_document.id,
        })

        if self.verdict == "cleared":
            latest_version_number = max(scope_document.version_ids.mapped("version_number") or [0])
            scope_document.version_ids.filtered(
                lambda version: version.version_number == latest_version_number
            ).write({"state": "cleared"})
            scope_document.version_ids.filtered(
                lambda version: version.version_number < latest_version_number
                and version.state != "abandoned"
            ).write({"state": "findings_open"})
            self.engagement_id.run_ids.mapped("finding_ids").filtered(
                lambda finding: finding.state in ("open", "regressed")
            ).write({
                "state": "resolved",
                "closed_in_run_id": self.id,
                "disposition": _("Cleared by the completed review cycle."),
                "disposition_by_id": self.env.user.id,
                "disposition_at": fields.Datetime.now(),
            })
            cycle.write({"state": "cleared", "cycle_count": cycle_number})
            return

        cycle.write({"cycle_count": cycle_number})
        cycle.action_guard_cycle()
        if cycle.state == "escalated":
            return
        directed_findings = [{
            "finding_key": finding.finding_key,
            "severity": finding.severity,
            "category": finding.category,
            "location": finding.location,
            "summary": finding.summary,
            "resolution_route": finding.resolution_route,
        } for finding in self.finding_ids.filtered(
            lambda finding: finding.state in ("open", "regressed")
            and finding.resolution_route == "regenerate"
        )]
        self._start_follow_up("gen-sow", {
            "automatic_flow": True,
            "cycle_number": cycle_number + 1,
            "directed_findings": directed_findings,
        })

    def _start_follow_up(self, skill_identifier, parameters):
        """Submit the next asynchronous run without making a completed run fail."""
        run = self.create({
            "engagement_id": self.engagement_id.id,
            "skill_identifier": skill_identifier,
            "source_set_revision": self.source_set_revision,
            "parameters_json": json.dumps(parameters),
        })
        try:
            run.action_submit()
        except (URLError, UserError, ValueError) as error:
            run.write({"state": "failed", "failure_code": "follow_up_submission_failed", "log_json": json.dumps({"message": str(error)})})
        return run

    def _import_status(self, status):
        self.ensure_one()
        version_numbers = {}
        for output in status.get("outputs", []):
            if self.output_ids.filtered(lambda item: item.filename == output["filename"]):
                continue
            data = self._download_output(output["download_url"])
            attachment = self.env["ir.attachment"].create({"name": output["filename"], "datas": base64.b64encode(data), "mimetype": output["media_type"], "res_model": "datum.run", "res_id": self.id})
            self.env["datum.run.output"].create({"run_id": self.id, "attachment_id": attachment.id, "filename": output["filename"], "document_type": output["document_type"], "distribution_class": output["distribution_class"]})
            document = self.env["datum.document"].search([( "engagement_id", "=", self.engagement_id.id), ("document_type", "=", output["document_type"])], limit=1) or self.env["datum.document"].create({"engagement_id": self.engagement_id.id, "document_type": output["document_type"]})
            next_version = version_numbers.setdefault(document.id, max(document.version_ids.mapped("version_number") or [0]) + 1)
            preview_attachment = False
            if output.get("preview_url"):
                preview_name = urlparse(output["preview_url"]).path.rsplit("/", 1)[-1]
                preview_attachment = self.env["ir.attachment"].create({
                    "name": preview_name,
                    "datas": base64.b64encode(self._download_output(output["preview_url"])),
                    "mimetype": "text/html",
                    "res_model": "datum.run",
                    "res_id": self.id,
                })
            self.env["datum.document.version"].create({"document_id": document.id, "version_number": next_version, "distribution_class": output["distribution_class"], "attachment_id": attachment.id, "preview_url": output.get("preview_url"), "preview_attachment_id": preview_attachment.id if preview_attachment else False, "generated_source_text": output.get("source_text"), "source_set_revision": self.source_set_revision, "run_id": self.id, "state": "in_review"})
        for finding in status.get("findings", []):
            existing = self.env["datum.finding"].search([( "engagement_id", "=", self.engagement_id.id), ("finding_key", "=", finding["finding_key"])], limit=1)
            values = {"engagement_id": self.engagement_id.id, "run_id": self.id, "finding_key": finding["finding_key"], "severity": finding["severity"], "category": finding["category"], "location": finding["location"], "summary": finding["summary"], "resolution_route": finding["resolution_route"], "state": "open" if status.get("verdict") == "not_cleared" else "resolved"}
            if existing:
                existing.write(values | {"state": "regressed" if existing.state == "resolved" and values["state"] == "open" else values["state"]})
            else:
                self.env["datum.finding"].create(values)

    def _download_output(self, relative_url):
        base_url = self.env["ir.config_parameter"].sudo().get_param("datum_engine.service_url", "http://127.0.0.1:5000")
        headers = {}
        token = self.env["ir.config_parameter"].sudo().get_param("datum_engine.api_auth_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(base_url.rstrip("/") + relative_url, headers=headers, method="GET")
        with urlopen(request, timeout=30) as response:
            return response.read()


class DatumRunOutput(models.Model):
    _name = "datum.run.output"
    _description = "Datum Run Output"
    run_id = fields.Many2one("datum.run", required=True, ondelete="cascade")
    attachment_id = fields.Many2one("ir.attachment", required=True, ondelete="restrict")
    filename = fields.Char(required=True)
    document_type = fields.Char(required=True)
    distribution_class = fields.Selection([("client_permitted", "Client Permitted"), ("internal_only", "Internal Only")], required=True)


class DatumFinding(models.Model):
    _name = "datum.finding"
    _description = "Persistent Datum Finding"
    _inherit = ["mail.thread"]
    finding_key = fields.Char(required=True, index=True)
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    run_id = fields.Many2one("datum.run", required=True, ondelete="cascade")
    severity = fields.Selection([("blocking", "Blocking"), ("advisory", "Advisory")], required=True)
    category = fields.Char(required=True)
    location = fields.Char(required=True)
    summary = fields.Text(required=True)
    resolution_route = fields.Selection([("regenerate", "Regenerate"), ("clarify", "Clarify"), ("waive", "Waive")], required=True)
    state = fields.Selection(FINDING_STATES, default="open", required=True, tracking=True)
    first_seen_run_id = fields.Many2one("datum.run", default=lambda self: self.run_id, readonly=True)
    closed_in_run_id = fields.Many2one("datum.run", readonly=True)
    disposition = fields.Text()
    disposition_by_id = fields.Many2one("res.users", readonly=True)
    disposition_at = fields.Datetime(readonly=True)

    def action_waive(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only an Odoo administrator may waive a finding."))
        self.write({"state": "waived", "disposition_by_id": self.env.user.id, "disposition_at": fields.Datetime.now(), "disposition": _("Waived by Odoo administrator.")})


class DatumReviewCycle(models.Model):
    _name = "datum.review.cycle"
    _description = "Generic Datum Review Cycle"
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    document_id = fields.Many2one("datum.document", required=True, ondelete="cascade")
    state = fields.Selection([("active", "Active"), ("awaiting_clarification", "Awaiting Clarification"), ("escalated", "Escalated"), ("cleared", "Cleared"), ("abandoned", "Abandoned")], default="active", required=True)
    cycle_count = fields.Integer(default=0)
    max_cycles = fields.Integer(default=5)
    escalation_reason = fields.Text()

    def action_guard_cycle(self):
        for record in self:
            if record.cycle_count >= record.max_cycles:
                record.write({"state": "escalated", "escalation_reason": _("Cycle ceiling reached.")})


class DatumQuestionSet(models.Model):
    _name = "datum.question.set"
    _description = "Datum Clarification Question Set"
    engagement_id = fields.Many2one("datum.engagement", required=True, ondelete="cascade")
    finding_ids = fields.Many2many("datum.finding")
    state = fields.Selection([("draft", "Draft"), ("issued", "Issued"), ("answered", "Answered")], default="draft")
    questions = fields.Text(required=True)
    answers = fields.Text()

    def action_issue(self):
        self.write({"state": "issued"})

    def action_register_answers(self):
        for record in self:
            if not record.answers:
                raise ValidationError(_("Enter the returned answers first."))
            self.env["datum.source.artifact"].create({"name": _("Clarification answers"), "engagement_id": record.engagement_id.id, "source_key": f"question-set-{record.id}", "revision": 1, "source_type": "clarification_answers", "content": record.answers})
            record.write({"state": "answered"})


class DatumRegenerateWizard(models.TransientModel):
    _name = "datum.regenerate.wizard"
    _description = "Edit and Regenerate Datum Document"

    document_version_id = fields.Many2one("datum.document.version", required=True, readonly=True)
    engagement_id = fields.Many2one(related="document_version_id.engagement_id", readonly=True)
    document_type = fields.Selection(related="document_version_id.document_type", readonly=True)
    instructions = fields.Text(required=True, string="Changes to make")

    def action_regenerate(self):
        self.ensure_one()
        if not self.instructions or not self.instructions.strip():
            raise UserError(_("Describe the changes you want before regenerating."))
        self.engagement_id._regenerate_document(
            self.document_type,
            self.instructions,
            self.document_version_id,
        )
        # The parent project form polls the queued run and shows the status
        # notification. Closing here keeps the wizard from blocking the user.
        return {"type": "ir.actions.act_window_close"}
