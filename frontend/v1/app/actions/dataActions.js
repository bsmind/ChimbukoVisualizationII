import axios from 'axios';

export function set_value(key, value) {
    return {
        type: "SET_VALUE",
        payload: {key, value}
    };
}

export function set_stats(newStats) {
    return {
        type: "SET_STATS",
        payload: newStats
    };
}

export function set_watched_rank(rank) {
    return {
        type: "SET_WATCHED_RANK",
        payload: rank
    };
}

export function unset_watched_rank(rank) {
    return {
        type: "UNSET_WATCHED_RANK",
        payload: rank
    };
}

export function get_execution(item) {
    return dispatch => {
        const {app, rank, step, min_timestamp, max_timestamp} = item;
        const arg1 = `pid=${app}&rid=${rank}&step=${step}`;
        const arg2 = `min_ts=${min_timestamp}&max_ts=${max_timestamp}`;
        const arg3 = `order=desc&with_comm=0`;
        const url = `/events/query_executions_file?${arg1}&${arg2}&${arg3}`;
        axios.get(url)
            .then(resp => {
                dispatch({
                    type: "SET_EXECUTION_DATA",
                    payload: {
                        config: item,
                        data: resp.data
                    }
                });
            })
            .catch(e => {
                dispatch({
                    type: "GET_EXECUTION_REJECTED",
                    payload: e
                });
            });
    };
}

