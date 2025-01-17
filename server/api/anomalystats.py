from flask import request, jsonify, abort, current_app

from .. import db
from ..models import AnomalyStat, AnomalyData, FuncStat, AnomalyStatQuery
from . import api
from ..tasks import make_async
from ..utils import timestamp, url_for
from requests import post
from ..events import push_data

from sqlalchemy.exc import IntegrityError
from runstats import Statistics
from sqlalchemy import func, and_


def process_on_anomaly(data:list, ts):
    """
    process on anomaly data before adding to database
    """
    anomaly_stat = []
    anomaly_data = []

    for d in data:
        if 'key' in d:
            app, rank = d['key'].split(':')
            app = int(app)
            rank = int(rank)
        else:
            app = d.get('app')
            rank = d.get('rank')
        key = '{}:{}'.format(app, rank)
        key_ts = '{}:{}'.format(key, ts)

        stat = d['stats']
        stat.update({
            'key': key,
            'key_ts': key_ts,
            'app': app,
            'rank': rank,
            'created_at': ts
        })
        anomaly_stat.append(stat)

        if 'data' in d:
            anomaly_data += d['data']

    return anomaly_stat, anomaly_data


def process_on_func(data:list, ts):
    def getStat(stat:dict, prefix):
        d = {}
        for k, v in stat.items():
            d["{}_{}".format(prefix, k)] = v
        return d

    func_stat = []
    for d in data:
        key_ts = '{}:{}'.format(d['fid'], ts)
        base = {
            'created_at': ts,
            'key_ts': key_ts,
            'fid': d['fid'],
            'name': d['name']
        }

        base.update(getStat(d['stats'], 'a'))
        base.update(getStat(d['inclusive'], 'i'))
        base.update(getStat(d['exclusive'], 'e'))

        func_stat.append(base)

    return func_stat


def delete_old_anomaly():
    subq = db.session.query(
        AnomalyStat.app,
        AnomalyStat.rank,
        func.max(AnomalyStat.created_at).label('max_ts')
    ).group_by(AnomalyStat.app, AnomalyStat.rank).subquery('t2')

    ret = [ [d.id, d.key_ts] for d in db.session.query(AnomalyStat).join(
        subq,
        and_(
            AnomalyStat.app == subq.c.app,
            AnomalyStat.rank == subq.c.rank,
            AnomalyStat.created_at < subq.c.max_ts
        )
    ).all()]

    ids = [q[0] for q in ret]
    keys = [q[1] for q in ret]

    db.engine.execute(
        AnomalyStat.__table__.delete().where(AnomalyStat.id.in_(ids))
    )
    # db.engine.execute(
    #     Stat.__table__.delete().where(Stat.anomalystat_key.in_(keys))
    # )


def delete_old_func():
    subq = db.session.query(
        FuncStat.fid,
        func.max(FuncStat.created_at).label('max_ts')
    ).group_by(FuncStat.fid).subquery('t2')

    ret = [[d.id, d.key_ts] for d in db.session.query(FuncStat).join(
        subq,
        and_(
            FuncStat.fid == subq.c.fid,
            FuncStat.created_at < subq.c.max_ts
        )
    ).all()]

    ids = [q[0] for q in ret]
    keys = list(set([q[1] for q in ret]))

    db.engine.execute(
        FuncStat.__table__.delete().where(FuncStat.id.in_(ids))
    )
    # db.engine.execute(
    #     Stat.__table__.delete().where(Stat.funcstat_key.in_(keys))
    # )


def push_anomaly_stat(q, anomaly_stats:list):

    # query arguments
    nQueries = q.nQueries
    statKind = q.statKind

    anomaly_stats.sort(key=lambda d: d[statKind], reverse=True)

    top_stats = []
    bottom_stats = []
    if anomaly_stats is not None and len(anomaly_stats):
        nQueries = min(nQueries, len(anomaly_stats))
        top_stats = anomaly_stats[:nQueries]
        bottom_stats = anomaly_stats[-nQueries:]

    # ---------------------------------------------------
    # processing data for the front-end
    # --------------------------------------------------
    if len(top_stats) and len(bottom_stats):
        top_dataset = {
            'name': 'TOP',
            'stat': top_stats,
        }
        bottom_dataset = {
            'name': 'BOTTOM',
            'stat': bottom_stats
        }

        # broadcast the statistics to all clients
        push_data({
            'nQueries': nQueries,
            'statKind': statKind,
            'data': [top_dataset, bottom_dataset]
        }, 'update_stats')


def push_anomaly_data(q, anomaly_data:list):
    q = q.to_dict()
    ranks = q.get('ranks', [])

    if len(ranks) == 0:
        return

    selected = list(filter(lambda d: d['rank'] in ranks, anomaly_data))
    selected.sort(key=lambda d: d['min_timestamp'])
    push_data(selected, 'update_history')


@api.route('/anomalydata', methods=['POST'])
@make_async
def new_anomalydata():
    """
    Register anomaly data

    - structure
    {
        "created_at": (integer),
        "anomaly": [
            {
                "key": "{app}:{rank}",   // app == pid, todo: append timestamp?
                "stats": {               // statistics
                    // todo: "anomalystat_key": "{app}:{rank}:{ts}"
                    "count": (integer),
                    "accumulate": (float),
                    "minimum": (float),
                    "maximum": (float),
                    "mean": (float),
                    "stddev": (float),
                    "skewness": (float),
                    "kurtosis": (float)
                },
                "data": [         // AnomalyData
                    {
                        "app": (integer),
                        "rank": (integer),
                        "step": (integer),
                        "min_timestamp": (integer),
                        "max_timestamp": (integer),
                        "n_anomalies": (integer),
                        "stat_id": (integer)  // must matched with "key"
                    }
                ]
            }
        ],
        "func": [
            {
                // todo: "funcstat_key": "{fid}:{ts}"
                "fid": (integer),
                "name": (string),
                "stats": { statistics },
                "inclusive": { statistics },
                "exclusive": { statistics }
            }
        ]
    }

    """
    # print('new_anomalydata')
    data = request.get_json() or {}

    ts = data.get('created_at', None)
    if ts is None:
        abort(400)

    # print('processing...')
    anomaly_stat, anomaly_data = \
        process_on_anomaly(data.get('anomaly', []), ts)
    func_stat = process_on_func(data.get('func', []), ts)

    # print('update db...')
    try:
        if len(anomaly_stat):
            db.get_engine(app=current_app, bind='anomaly_stats').execute(
                AnomalyStat.__table__.insert(), anomaly_stat
            )
            db.get_engine(app=current_app, bind='anomaly_data').execute(
                AnomalyData.__table__.insert(), anomaly_data
            )
        if len(func_stat):
            db.get_engine(app=current_app, bind='func_stats').execute(
                FuncStat.__table__.insert(), func_stat
            )

        # although we have defined models to enable cascased delete operation,
        # it actually didn't work. The reason is that we do the bulk insertion
        # to get performance and, for now, I couldn't figure out how to define
        # backreference in the above bulk insertion. So that, we do delete
        # Stat rows manually (but using bulk deletion)

        # currently this is error prone!!!

        #delete_old_anomaly()
        #delete_old_func()
    except Exception as e:
        print(e)

    try:
        # get query condition from database
        q = AnomalyStatQuery.query. \
            order_by(AnomalyStatQuery.created_at.desc()).first()

        if q is None:
            q = AnomalyStatQuery.create({
                'nQueries': 5,
                'statKind': 'stddev',
                'ranks': []
            })
            db.session.add(q)
            db.session.commit()

        if len(anomaly_stat):
            push_anomaly_stat(q, anomaly_stat)

        if len(anomaly_data):
            push_anomaly_data(q, anomaly_data)

    except Exception as e:
        print(e)

    # todo: make information output with Location
    return jsonify({}), 201


@api.route('/get_anomalystats', methods=['GET'])
def get_anomalystats():
    """
    Return anomaly stat specified by app and rank index
    - (e.g.) /api/anomalystats will return all available statistics
    - (e.g.) /api/anomalystats?app=0&rank=0 will return statistics of
                 application index is 0 and rank index is 0.
    - return 400 error if there are no available statistics
    """
    # get query condition from database
    query = AnomalyStatQuery.query. \
        order_by(AnomalyStatQuery.created_at.desc()).first()

    if query is None:
        query = AnomalyStatQuery.create({
            'nQueries': 5,
            'statKind': 'stddev',
            'ranks': []
        })
        db.session.add(query)
        db.session.commit()

    subq = db.session.query(
        AnomalyStat.app,
        AnomalyStat.rank,
        func.max(AnomalyStat.created_at).label('max_ts')
    ).group_by(AnomalyStat.app, AnomalyStat.rank).subquery('t2')

    stats = db.session.query(AnomalyStat).join(
        subq,
        and_(
            AnomalyStat.app == subq.c.app,
            AnomalyStat.rank == subq.c.rank,
            AnomalyStat.created_at == subq.c.max_ts
        )
    ).all()

    push_anomaly_stat(query, [st.to_dict() for st in stats])
    return jsonify({}), 200
    #return jsonify([st.to_dict() for st in stats])


@api.route('/run_simulation', methods=['GET'])
@make_async
def run_simulation():
    import time
    error = 'OK'
    try:
        step_ts = int(1000000)
        min_timestamp = db.session.query(func.min(AnomalyData.max_timestamp))\
            .filter(AnomalyData.max_timestamp > 0).scalar()
        max_timestamp = db.session.query(func.max(AnomalyData.max_timestamp))\
            .filter(AnomalyData.max_timestamp > 0).scalar()
        min_timestamp = int(min_timestamp)
        max_timestamp = int(max_timestamp)
        # print("min_timestamp: ", min_timestamp)
        # print("max_timestamp: ", max_timestamp)
        for ts in range(min_timestamp, max_timestamp+step_ts, step_ts):
            data = AnomalyData.query.filter(
                and_(
                    AnomalyData.max_timestamp >= ts,
                    AnomalyData.max_timestamp < ts + step_ts
                )
            )
            data = [d.to_dict() for d in data.all()]

            q = AnomalyStatQuery.query. \
                order_by(AnomalyStatQuery.created_at.desc()).first()

            if q is None:
                q = AnomalyStatQuery.create({
                    'nQueries': 5,
                    'statKind': 'stddev',
                    'ranks': []
                })
                db.session.add(q)
                db.session.commit()

            # print("ts: {}, data: {}", ts, len(data))
            if len(data):
                push_anomaly_data(q, data)

            time.sleep(1)
    except Exception as e:
        print('Exception on run simulation: ', e)
        error = 'exception while running simulation'
        pass

    push_data({'result': error}, 'run_simulation')

    return jsonify({})

@api.route('/get_anomalydata', methods=['GET'])
def get_anomalydata():
    app = request.args.get('app', default=None)
    rank = request.args.get('rank', default=None)
    limit = request.args.get('limit', default=None)

    stat = AnomalyStat.query.filter(
        and_(
            AnomalyStat.app==int(app),
            AnomalyStat.rank==int(rank)
        )
    ).order_by(
        AnomalyStat.created_at.desc()
    ).first()

    if limit is None:
        data = stat.hist.order_by(AnomalyData.step.desc()).all()
    else:
        data = stat.hist.order_by(AnomalyData.step.desc()).limit(limit).all()
    data.reverse()

    return jsonify([dd.to_dict() for dd in data])


@api.route('/get_funcstats', methods=['GET'])
def get_funcstats():
    fid = request.args.get('fid', default=None)

    subq = db.session.query(
        FuncStat.fid,
        func.max(FuncStat.created_at).label('max_ts')
    ).group_by(FuncStat.fid).subquery('t2')

    q = db.session.query(FuncStat).join(
        subq,
        and_(
            FuncStat.fid == subq.c.fid,
            FuncStat.created_at == subq.c.max_ts
        )
    )

    if fid is None:
        stats = q.all()
    else:
        stats = q.filter(FuncStat.fid == int(fid)).all()

    return jsonify([st.to_dict() for st in stats])
