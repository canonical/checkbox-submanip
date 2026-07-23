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

metadata = {"checkbox_version": checkbox_version, "submanip_version": __version__}

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'  # required for flash messages


@app.context_processor
def job_result():
    """Provide job information to the Flask template"""
    return  dict(job_result=IJobResult, job_outcome=outcome_meta)


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


if __name__ == "__main__":
    app.run(port=3001)