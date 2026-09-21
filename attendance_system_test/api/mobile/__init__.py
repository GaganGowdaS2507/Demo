from flask import Blueprint

mobile_bp = Blueprint("mobile", __name__)

from . import login
from . import embeddings
from . import sync
from . import sessions
from . import profile
from . import fingerprints