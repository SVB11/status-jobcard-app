/* Staff-facing unit ID: stock_number as stored, or job_number if that is blank. */
(function (w) {
    function jobDisplayId(j) {
        if (!j) return '';
        if (j.display_id) return j.display_id;
        var stock = (j.stock_number || '').trim();
        return stock || (j.job_number || '');
    }
    function jobDisplayHint(j) {
        if (!j) return '';
        return j.display_hint || '';
    }
    function jobDisplayLabel(j) {
        var id = jobDisplayId(j);
        var hint = jobDisplayHint(j);
        return hint ? (id + ' · ' + hint) : id;
    }
    w.jobDisplayId = jobDisplayId;
    w.jobDisplayHint = jobDisplayHint;
    w.jobDisplayLabel = jobDisplayLabel;
})(window);
