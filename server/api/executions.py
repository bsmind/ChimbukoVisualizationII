from flask import request, abort, jsonify, json, current_app
import os
from .. import db
from ..tasks import make_async
from ..models import ExecData, CommData

from . import api


@api.route('/executions', methods=['POST'])
@make_async
def new_executions():
    """
    Register a list of new executions

    - structure
    {
        "exec": [
            {
                "key": (string),
                "name": (integer),
                "pid": (integer),
                "rid": (integer),
                "tid": (integer),
                "fid": (integer),
                "entry": (integer),
                "exit": (integer),
                "runtime": (integer),
                "exclusive": (integer),
                "label": (integer), // 1: normal, -1: abnormal
                "parent": (string),   // "key" of parent
                "n_children": (integer),
                "n_messages": (integer)
            }
        ],
        "comm": [
            {
                todo: "execdata_key": "id"
                "type": (string),  // SEND or RECV
                "pid": (integer),
                "rid": (integer),
                "tid": (integer),
                "src": (integer),
                "tar": (integer),
                "bytes": (integer),
                "tag": (integer),
                "timestamp": (integer),
                "fid": (integer),
                "name": (string)
            }
        ]
    }
    """
    try:
        data = request.get_json() or {}

        # execdata = data.get('exec', [])
        # commdata = data.get('comm', [])
        app = data.get('app', None)
        rank = data.get('rank', None)
        step = data.get('step', None)
        path = current_app.config.get('EXECUTION_PATH', None)

        if all(v is not None for v in [app, rank, step, path]):
            path = os.path.join(
                path,
                '{}'.format(app),
                '{}'.format(rank)
            )
            if not os.path.exists(path):
                os.makedirs(path)

            with open(os.path.join(path, '{}.json'.format(step)), 'w') as f:
                json.dump(data, f)

            # with open(os.path.join(path, 'comm-{}.json'.format(step)), 'w') as f:
            #     json.dump(commdata, f)


        # if len(execdata):
        #     db.engine.execute(ExecData.__table__.insert(), execdata)

        # if len(commdata):
        #     db.engine.execute(CommData.__table__.insert(), commdata)

    except Exception as e:
        print("Exception on /executions POST: ", e)
        pass

    return jsonify({}), 201


@api.route('/get_executions', methods=['GET'])
def get_executions():
    """
    Return a list of execution data within a given time range
    - required:
        min_ts: minimum timestamp
    - options
        max_ts: maximum timestamp
        order: [(asc) | desc]
        with_comm: 1 or (0)
        pid: program index, default None
        rid: rank index, default None
    """
    min_ts = request.args.get('min_ts', None)
    if min_ts is None:
        abort(400)

    # parse options
    max_ts = request.args.get('max_ts', None)
    order = request.args.get('order', 'asc')
    with_comm = request.args.get('with_comm', 0)
    pid = request.args.get('pid', None)
    rid = request.args.get('rid', None)

    execdata = ExecData.query.filter(ExecData.entry >= min_ts)
    if max_ts is not None:
        execdata = execdata.filter(ExecData.exit <= max_ts)

    if pid is not None:
        execdata = execdata.filter(ExecData.pid == pid)

    if rid is not None:
        execdata = execdata.filter(ExecData.rid == rid)

    if order == 'asc':
        execdata = execdata.order_by(ExecData.entry.asc())
    else:
        execdata = execdata.order_by(ExecData.entry.desc())

    return jsonify([d.to_dict(with_comm) for d in execdata.all()])
