"""Submanip: a native GTK4 + libadwaita editor for Checkbox submission archives."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tarfile
from logging.handlers import RotatingFileHandler
from tempfile import mkdtemp
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from checkbox_ng import __version__ as checkbox_version  # noqa: E402
from plainbox.abc import IJobResult  # noqa: E402
from plainbox.impl.result import outcome_meta  # noqa: E402
from submission_utils import CheckboxSubmission  # noqa: E402

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = RotatingFileHandler("submanip.log", maxBytes=5 * 1024 * 1024, backupCount=2)
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
logger.addHandler(fh)

__version__ = "1.0"
APP_ID = "io.canonical.checkbox.Submanip"

# Every possible job outcome, in the same order Checkbox itself exposes them.
OUTCOMES: list[str | None] = [
    getattr(IJobResult, k) for k in dir(IJobResult) if k.startswith("OUTCOME")
]


def outcome_label(outcome: str | None) -> str:
    """A human-friendly, never-empty label for a (possibly None) outcome."""
    return "none" if outcome is None else outcome


def outcome_css_class(outcome: str | None) -> str:
    return "outcome-" + outcome_label(outcome).replace("_", "-")


class OutcomeOption(GObject.Object):
    """A single choice in the outcome drop-down."""

    value = GObject.Property(type=object)
    label = GObject.Property(type=str)

    def __init__(self, value: str | None) -> None:
        super().__init__()
        self.value = value
        self.label = outcome_label(value)


class ResultRow(GObject.Object):
    """GObject wrapper around one job result, bound to a ColumnView row."""

    full_id = GObject.Property(type=str)
    display_id = GObject.Property(type=str)
    category = GObject.Property(type=str)
    cert_status = GObject.Property(type=str)
    comment = GObject.Property(type=str)
    outcome = GObject.Property(type=object)

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__()
        self.full_id = result["full_id"]
        self.display_id = result.get("id", result["full_id"])
        self.category = result.get("category", "")
        self.cert_status = result.get("certification_status", "")
        self.comment = result.get("comments") or ""
        self.outcome = result.get("outcome")


def build_outcome_css() -> Gtk.CssProvider:
    """Style provider giving each outcome drop-down its Checkbox colour and
    making every editable cell in the results table (comment entries and the
    outcome drop-downs) share the same rounded-corner look."""
    provider = Gtk.CssProvider()
    rules: list[str] = [
        ".submanip-cell, .submanip-cell button {"
        " border-radius: 6px;"
        " min-height: 24px;"
        "}",
        ".submanip-cell {"
        " margin: 2px;"
        "}",
    ]
    for outcome in OUTCOMES:
        meta = outcome_meta(outcome)
        rules.append(
            ".{cls}, .{cls} button {{"
            " background-color: {color};"
            " background-image: none;"
            " color: white;"
            " border-radius: 6px;"
            "}}".format(cls=outcome_css_class(outcome), color=meta.color_hex)
        )
    provider.load_from_string("\n".join(rules))
    return provider


class SubmanipWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Checkbox Submission Editor")
        self.set_default_size(1100, 750)

        self.outcome_model: Gio.ListStore[OutcomeOption] = Gio.ListStore(item_type=OutcomeOption)
        for outcome in OUTCOMES:
            self.outcome_model.append(OutcomeOption(outcome))

        self.temp_arc: str | None = None
        self.list_store: Gio.ListStore[ResultRow] = Gio.ListStore(item_type=ResultRow)
        self.visible_outcomes: set[str | None] = set(OUTCOMES)
        self.search_text: str = ""
        self.result_filter: Gtk.CustomFilter | None = None
        self.title_entry: Adw.EntryRow | None = None
        self.description_view: Gtk.TextView | None = None

        self.toast_overlay = Adw.ToastOverlay()
        self.nav_view = Adw.NavigationView()
        self.toast_overlay.set_child(self.nav_view)
        self.set_content(self.toast_overlay)

        self.nav_view.add(self._build_welcome_page())

    # -- Welcome page --------------------------------------------------

    def _build_welcome_page(self) -> Adw.NavigationPage:
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            hexpand=True,
            vexpand=True,
        )
        icon = Gtk.Image.new_from_icon_name("document-edit-symbolic")
        icon.set_pixel_size(64)
        box.append(icon)

        title = Gtk.Label(label="Checkbox Submission Editor")
        title.add_css_class("title-1")
        box.append(title)

        instructions = Gtk.Label(
            label=(
                "Select a Checkbox submission archive (submission.tar.xz)\n"
                "to edit its test results and comments, then save the\n"
                "changes as a new submission archive."
            ),
            justify=Gtk.Justification.CENTER,
            wrap=True,
        )
        instructions.add_css_class("dim-label")
        box.append(instructions)

        open_button = Gtk.Button(label="Open Submission…")
        open_button.add_css_class("suggested-action")
        open_button.add_css_class("pill")
        open_button.set_halign(Gtk.Align.CENTER)
        open_button.connect("clicked", self.on_open_clicked)
        box.append(open_button)

        version_label = Gtk.Label(
            label=f"submanip v{__version__} (using checkbox-ng v{checkbox_version})"
        )
        version_label.add_css_class("dim-label")
        version_label.add_css_class("caption")
        box.append(version_label)

        banner = Adw.Banner(
            title="Submissions edited with this tool should NOT be uploaded to C3."
        )
        banner.set_revealed(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(banner)
        content.append(box)
        toolbar_view.set_content(content)

        return Adw.NavigationPage(child=toolbar_view, title="Submanip", tag="welcome")

    def on_open_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Select a Checkbox submission archive")
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Checkbox submission archive (*.tar.xz)")
        file_filter.add_pattern("*.tar.xz")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_open_dialog_done)

    def _on_open_dialog_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error as e:
            if not e.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                logger.warning("File open dialog failed: %s", e)
            return
        
        filepath = gfile.get_path()
        assert filepath
        self.load_submission(filepath)

    def load_submission(self, path: str) -> None:
        tmpdir = mkdtemp(prefix="submanip-open-")
        temp_arc = os.path.join(tmpdir, os.path.basename(path))
        try:
            shutil.copyfile(path, temp_arc)
            with tarfile.open(temp_arc) as tar:
                tar.extractall(tmpdir, filter="data")
            with open(os.path.join(tmpdir, "submission.json")) as s:
                data: dict[str, Any] = json.load(s)
        except (OSError, tarfile.TarError, ValueError):
            logger.exception("Failed to open submission %s", path)
            self.toast_overlay.add_toast(Adw.Toast(title="Incorrect submission file!"))
            return

        logger.debug(
            "Editing submission `%s` (%s) [build: %s]",
            data.get("title", "no title"),
            data.get("description", "no description"),
            data.get("buildstamp", "no buildstamp"),
        )

        self.temp_arc = temp_arc
        self.nav_view.push(self._build_edit_page(data))

    # -- Edit page -------------------------------------------------------

    def _build_edit_page(self, data: dict[str, Any]) -> Adw.NavigationPage:
        self.list_store.remove_all()
        for result in data.get("results", []):
            self.list_store.append(ResultRow(result))

        self.visible_outcomes = set(OUTCOMES)
        self.search_text = ""
        self.result_filter = Gtk.CustomFilter.new(self._filter_func)
        filter_model = Gtk.FilterListModel(model=self.list_store, filter=self.result_filter)
        selection_model = Gtk.NoSelection(model=filter_model)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        window_title = Adw.WindowTitle(
            title=data.get("title", ""), subtitle="Editing Checkbox submission"
        )
        header.set_title_widget(window_title)

        save_button = Gtk.Button(label="Save As…")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self.on_save_clicked)
        header.pack_end(save_button)
        toolbar_view.add_top_bar(header)

        self.title_entry = Adw.EntryRow(title="Session name")
        self.title_entry.set_text(data.get("title", ""))

        self.description_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD)
        self.description_view.set_top_margin(8)
        self.description_view.set_bottom_margin(8)
        self.description_view.set_left_margin(8)
        self.description_view.set_right_margin(8)
        self.description_view.get_buffer().set_text(data.get("description", "") or "")
        description_frame = Gtk.ScrolledWindow(
            min_content_height=100, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        description_frame.set_child(self.description_view)
        description_frame.add_css_class("frame")
        description_frame.set_overflow(Gtk.Overflow.HIDDEN)
        description_row = Adw.ActionRow()
        description_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        description_label = Gtk.Label(label="Session description", xalign=0)
        description_label.add_css_class("dim-label")
        description_box.append(description_label)
        description_box.append(description_frame)
        description_row.set_child(description_box)

        details_expander = Adw.ExpanderRow(
            title="Session details", subtitle=data.get("title", "")
        )
        details_expander.add_row(self.title_entry)
        details_expander.add_row(description_row)

        info_group = Adw.PreferencesGroup()
        info_group.add(details_expander)

        # Compact search + outcome-filter row, kept above the results table.
        search_entry = Gtk.SearchEntry(
            placeholder_text="Filter by job ID…", hexpand=True
        )
        search_entry.connect("search-changed", self._on_search_changed)

        filter_popover = Gtk.Popover()
        filter_flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=3,
            homogeneous=False,
            row_spacing=6,
            column_spacing=12,
            margin_top=6,
            margin_bottom=6,
            margin_start=6,
            margin_end=6,
        )
        for outcome in OUTCOMES:
            check = Gtk.CheckButton(label=outcome_label(outcome).capitalize())
            check.set_active(True)
            check.set_halign(Gtk.Align.START)
            check.connect("toggled", self._on_filter_toggled, outcome)
            filter_flow.append(check)
        filter_popover.set_child(filter_flow)

        filter_button = Gtk.MenuButton(
            icon_name="funnel-symbolic", tooltip_text="Filter by test status"
        )
        filter_button.set_popover(filter_popover)

        toolbar_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar_row.append(search_entry)
        toolbar_row.append(filter_button)

        column_view = self._build_column_view(selection_model)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(column_view)
        scroller.add_css_class("frame")
        scroller.set_overflow(Gtk.Overflow.HIDDEN)

        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        results_box.append(toolbar_row)
        results_box.append(scroller)
        results_box.set_vexpand(True)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        content.append(info_group)
        content.append(results_box)
        toolbar_view.set_content(content)

        return Adw.NavigationPage(
            child=toolbar_view, title=data.get("title", "Edit"), tag="edit"
        )

    def _build_column_view(self, selection_model: Gtk.SelectionModel) -> Gtk.ColumnView:
        column_view = Gtk.ColumnView(model=selection_model, vexpand=True)

        column_view.append_column(
            self._make_label_column("ID", "display_id", expand=True)
        )
        column_view.append_column(
            self._make_label_column("Category", "category")
        )
        column_view.append_column(self._make_outcome_column())
        column_view.append_column(
            self._make_label_column("Cert Status", "cert_status")
        )
        column_view.append_column(self._make_comment_column())
        return column_view

    def _make_label_column(
        self, title: str, prop_name: str, expand: bool = False
    ) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()

        def setup(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            label = Gtk.Label(xalign=0, wrap=True)
            list_item.set_child(label)

        def bind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            row: ResultRow = list_item.get_item()
            label: Gtk.Label = list_item.get_child()
            label.set_label(getattr(row, prop_name) or "")

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        column = Gtk.ColumnViewColumn(title=title, factory=factory)
        column.set_expand(expand)
        column.set_resizable(True)
        return column

    def _make_outcome_column(self) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()

        def setup(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            dropdown = Gtk.DropDown(model=self.outcome_model)
            expression = Gtk.PropertyExpression.new(OutcomeOption, None, "label")
            dropdown.set_expression(expression)
            dropdown.add_css_class("submanip-cell")
            list_item.set_child(dropdown)

        def bind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            row: ResultRow = list_item.get_item()
            dropdown: Gtk.DropDown = list_item.get_child()
            dropdown.set_selected(self._outcome_index(row.outcome))
            self._style_outcome_dropdown(dropdown, row.outcome)
            handler_id = dropdown.connect(
                "notify::selected", self._on_outcome_changed, row
            )
            dropdown._submanip_handler_id = handler_id

        def unbind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            dropdown: Gtk.DropDown = list_item.get_child()
            handler_id = getattr(dropdown, "_submanip_handler_id", None)
            if handler_id is not None:
                dropdown.disconnect(handler_id)
                dropdown._submanip_handler_id = None

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        column = Gtk.ColumnViewColumn(title="Result", factory=factory)
        column.set_resizable(True)
        return column

    def _make_comment_column(self) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()

        def setup(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            entry = Gtk.Entry(hexpand=True)
            entry.add_css_class("submanip-cell")
            list_item.set_child(entry)

        def bind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            row: ResultRow = list_item.get_item()
            entry: Gtk.Entry = list_item.get_child()
            entry.set_text(row.comment or "")
            handler_id = entry.connect(
                "changed", lambda e, r=row: setattr(r, "comment", e.get_text())
            )
            entry._submanip_handler_id = handler_id

        def unbind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
            entry: Gtk.Entry = list_item.get_child()
            handler_id = getattr(entry, "_submanip_handler_id", None)
            if handler_id is not None:
                entry.disconnect(handler_id)
                entry._submanip_handler_id = None

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        column = Gtk.ColumnViewColumn(title="Comment", factory=factory)
        column.set_expand(True)
        column.set_resizable(True)
        return column

    def _outcome_index(self, outcome: str | None) -> int:
        for i, candidate in enumerate(OUTCOMES):
            if candidate == outcome:
                return i
        return 0

    def _style_outcome_dropdown(self, dropdown: Gtk.DropDown, outcome: str | None) -> None:
        for candidate in OUTCOMES:
            dropdown.remove_css_class(outcome_css_class(candidate))
        dropdown.add_css_class(outcome_css_class(outcome))

    def _on_outcome_changed(
        self, dropdown: Gtk.DropDown, _pspec: GObject.ParamSpec, row: ResultRow
    ) -> None:
        option: OutcomeOption = self.outcome_model.get_item(dropdown.get_selected())
        row.outcome = option.value
        self._style_outcome_dropdown(dropdown, option.value)
        self.result_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_filter_toggled(self, check: Gtk.CheckButton, outcome: str | None) -> None:
        if check.get_active():
            self.visible_outcomes.add(outcome)
        else:
            self.visible_outcomes.discard(outcome)
        self.result_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_search_changed(self, search_entry: Gtk.SearchEntry) -> None:
        self.search_text = search_entry.get_text().strip().lower()
        self.result_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _filter_func(self, row: ResultRow) -> bool:
        if row.outcome not in self.visible_outcomes:
            return False
        if self.search_text and self.search_text not in row.display_id.lower():
            return False
        return True

    # -- Saving ------------------------------------------------------------

    def on_save_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Save edited submission as")
        dialog.set_initial_name("submanip-" + os.path.basename(self.temp_arc))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Checkbox submission archive (*.tar.xz)")
        file_filter.add_pattern("*.tar.xz")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.save(self, None, self._on_save_dialog_done)

    def _on_save_dialog_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error as e:
            if not e.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                logger.warning("File save dialog failed: %s", e)
            return

        filepath = gfile.get_path()
        assert filepath
        self._write_submission(filepath)

    def _write_submission(self, dest_path: str) -> None:
        buffer = self.description_view.get_buffer()
        description = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )
        form_data: dict[str, Any] = {
            "session-title": self.title_entry.get_text(),
            "session-description": description,
        }
        for i in range(self.list_store.get_n_items()):
            row: ResultRow = self.list_store.get_item(i)
            form_data[row.full_id + "-outcome"] = row.outcome
            form_data[row.full_id + "-comment"] = row.comment

        try:
            submission = CheckboxSubmission(self.temp_arc, form_data)
            shutil.copyfile(submission.output_file, dest_path)
        except Exception as e:
            logger.exception("Failed to save submission")
            self.toast_overlay.add_toast(Adw.Toast(title=f"Failed to save: {e}"))
            return

        self.toast_overlay.add_toast(Adw.Toast(title="Submission saved"))


class SubmanipApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.style_provider: Gtk.CssProvider = build_outcome_css()

    def do_activate(self) -> None:
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        window: Optional[Gtk.Window] = self.props.active_window
        if not window:
            window = SubmanipWindow(self)
        window.present()


def main() -> int:
    app = SubmanipApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
