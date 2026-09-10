# the background worker: one QObject whose work is split by responsibility across this package
from mahad.worker.poll import PollWorker as PollWorker
from mahad.worker.poll import _interrupted as _interrupted
