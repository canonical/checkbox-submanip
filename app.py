import json
import logging
from logging.handlers import RotatingFileHandler
import os.path
import tarfile
from tempfile import mkdtemp

from flask import (
    Flask,
    redirect,
    request,
    render_template,
    url_for,
    flash,
    send_from_directory,
)
from werkzeug.exceptions import BadRequestKeyError

from checkbox_ng import __version__ as checkbox_version
from plainbox.abc import IJobResult
from plainbox.impl.result import outcome_meta
from submission_utils import CheckboxSubmission

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = RotatingFileHandler("submanip.log", maxBytes=5 * 1024 * 1024, backupCount=2)
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
logger.addHandler(fh)

__version__ = "1.0"

metadata = {
    "checkbox_version": checkbox_version,
    "submanip_version": __version__,
}

app = Flask(__name__)
DEFAULT_PORT = 3001


@app.context_processor
def job_result():
    """Provide job information to the Flask template"""
    outcomes = [
        getattr(IJobResult, k) for k in dir(IJobResult) if k.startswith("OUTCOME")
    ]
    return dict(
        job_result=IJobResult,
        job_outcome=outcome_meta,
        job_result_outcomes=outcomes,
    )


@app.route("/", methods=("GET", "POST"))
def index():
    # Coming back from edition page with data to save into new JSON file
    if request.method == "POST":
        form_data = request.form
        filename = form_data.get("archive")
        output_file = CheckboxSubmission(filename, form_data).output_file
        return send_from_directory(
            os.path.dirname(output_file),
            os.path.basename(output_file),
            as_attachment=True,
        )
    # In any case, we render the index page
    return render_template("index.html", metadata=metadata)


@app.route("/edit", methods=("GET", "POST"))
def subedit():
    if request.method == "POST":
        tmpdir = mkdtemp()
        f = request.files["submission"]
        assert f.filename
        temp_arc = os.path.join(tmpdir, f.filename)
        f.save(temp_arc)
        try:
            with tarfile.open(temp_arc) as tar:
                tar.extractall(tmpdir)
                with open(os.path.join(tmpdir, "submission.json")) as s:
                    sub = s.read()
        except BadRequestKeyError:
            flash("Incorrect submission file!", "error")
            return redirect(url_for("index"))
        data = json.loads(sub)
        logger.debug(
            "Editing submission `{title}` ({desc}) [build: {build}]".format(
                title=data.get("title", "no title"),
                desc=data.get("description", "no description"),
                build=data.get("buildstamp", "no buildstamp"),
            )
        )
        return render_template("sub.html", data=data, archive=temp_arc)
    else:
        return redirect(url_for("index"))


def get_port():
    """Determine the port to listen on.

    Priority order:
    1. The `PORT` environment variable, if set to a valid integer.
    2. The value written by the snap's `configure` hook to
       `$SNAP_DATA/port` (populated via `snap set checkbox-submanip
       port=<port>`).
    3. DEFAULT_PORT.
    """
    port_env = os.environ.get("PORT")
    if port_env:
        try:
            return int(port_env)
        except ValueError:
            logger.warning("Ignoring invalid PORT env var: %r", port_env)

    snap_data = os.environ.get("SNAP_DATA")
    if snap_data:
        port_file = os.path.join(snap_data, "port")
        try:
            with open(port_file) as f:
                return int(f.read().strip())
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as e:
            logger.warning("Ignoring invalid port file %s: %s", port_file, e)

    return DEFAULT_PORT


if __name__ == "__main__":
    app.run(port=get_port())
