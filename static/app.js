/**
 * app.js - ダッシュボードの表示ロジック
 *
 * 状態(state) / 通信(api) / 描画(ui) / 操作(actions) に責務を分けている。
 * アプリ名はウィンドウタイトル由来の任意の文字列を含むため、DOMへの反映は
 * 必ず textContent か dataset を経由し、HTMLとして解釈させない。
 */

// ── 定数 ──

const CONFIG = {
    // 使用時間は分単位でしか変化しないため、頻繁な更新は不要
    REFRESH_INTERVAL: 15000,
    CHART_REFRESH_INTERVAL: 60000,
    // グラフに表示する下限（分）と最大件数
    CHART_MIN_MINUTES: 10,
    CHART_MAX_ITEMS: 10,
    CHART_LABEL_LENGTH: 8,
};

// 制限まで残りこの秒数を切ったら色を変える（通知の予告と同じ5分）
const LIMIT_NEAR_SECONDS = 300;

// 期間ごとの、増減に添える言葉
const LABELS = {
    diff: { day: '前日比', week: '前週比', month: '前月比' },
};

/**
 * グラフの配色。値は style.css の :root から読む
 *
 * Chart.js は CSS 変数を解釈しないため、ここで実際の色へ変換して渡す。
 * 参照は初回に評価される（読み込み時点ではまだ様式が適用されていないことがある）。
 */
const COLORS = {
    get text() { return theme.color('--text'); },
    get textSub() { return theme.color('--text-sub'); },
    get textMuted() { return theme.color('--text-muted'); },
    get border() { return theme.color('--border'); },
    get grid() { return theme.color('--bg-active'); },
    get surface() { return theme.color('--bg'); },
    // 使用時間の多い順に濃くする。色ではなく濃淡で大小を表す
    get bars() { return theme.scale('--bar-', 6); },
};

// ── 状態 ──

const state = {
    currentPeriod: 'day',
    // 表示中の日付。日付操作で切り替える
    date: '',
    chart: null,
    chartLabels: [],
    todayData: [],
    // 今日の実時間（重なりを除いた合計）と端末ごとの内訳
    todaySummary: null,
    limits: [],
    // グラフの各項目に対応する端末別の秒数
    chartDevices: [],
    selectedMinutes: null,
};

// ── DOM参照 ──

const nodes = {
    totalToday: document.getElementById('totalToday'),
    totalDiff: document.getElementById('totalDiff'),
    appCount: document.getElementById('appCount'),
    overLimitCount: document.getElementById('overLimitCount'),
    limitApp: document.getElementById('limitApp'),
    limitsList: document.getElementById('limitsList'),
    usageChart: document.getElementById('usageChart'),
    deviceNote: document.getElementById('deviceNote'),
    usageTitle: document.getElementById('usageTitle'),
    limitForm: document.getElementById('limitForm'),
    presets: document.querySelectorAll('.preset-btn'),
    tabs: document.querySelectorAll('.tab-btn'),
};

// ── ユーティリティ ──

const utils = {
    /** 順位に応じた棒の色を返す（上位ほど濃い） */
    barColor(index) {
        return COLORS.bars[Math.min(index, COLORS.bars.length - 1)];
    },
};

// ── 描画 ──

const ui = {
    updateSummary() {
        // 実時間・アプリ数・超過は、いずれも期間の解釈が要るためAPIで求める。
        // 画面側で足し上げると同時使用が二重に数えられ、
        // 制限の判定も日ごとに見る必要があるため
        const summary = state.todaySummary;
        if (!summary) return;

        nodes.totalToday.textContent = format.duration(summary.total_seconds);
        // 同時に使っていた時間があれば、その分を控えめに添える
        nodes.totalToday.title = summary.overlap_seconds > 0
            ? `単純な合計 ${format.duration(summary.simple_total_seconds)}`
                + `（うち同時使用 ${format.duration(summary.overlap_seconds)} を除いています）`
            : '';

        this.updateDiff(summary);
        nodes.appCount.textContent = String(summary.app_count);

        const overLimit = summary.over_limit_count;
        nodes.overLimitCount.textContent = String(overLimit);
        nodes.overLimitCount.title = summary.period === 'day'
            ? '制限時間を超えたアプリの数'
            : 'この期間に1日でも制限時間を超えたアプリの数';
        // 超過が発生している場合のみ着色する
        nodes.overLimitCount.classList.toggle('alert', overLimit > 0);
    },

    /** 1つ前の同じ長さの期間と比べた増減を出す */
    updateDiff(summary) {
        if (!nodes.totalDiff) return;

        // 比較できる記録が無い期間は、増減を出しても意味が無い
        if (summary.previous_seconds === undefined || summary.previous_seconds === 0) {
            nodes.totalDiff.textContent = '';
            nodes.totalDiff.title = '';
            return;
        }

        nodes.totalDiff.textContent = `${LABELS.diff[summary.period]} ${format.diff(summary.diff_seconds)}`;

        const singleDay = summary.previous_start === summary.previous_end;
        const range = singleDay
            ? format.shortDate(summary.previous_start)
            : `${format.shortDate(summary.previous_start)}〜${format.shortDate(summary.previous_end)}`;
        // 途中の期間は前の期間を切り詰めて比べるため、対象の範囲を添える
        nodes.totalDiff.title = `${range} の ${format.duration(summary.previous_seconds)} と比べています`
            + (singleDay ? '' : '（今の期間と同じ日数で比べます）');
    },

    updateAppSelect() {
        const select = nodes.limitApp;
        const selected = select.value;

        // 先頭のプレースホルダー以外を作り直す
        while (select.options.length > 1) select.remove(1);

        state.todayData.forEach((item) => {
            const option = document.createElement('option');
            option.value = item.app;
            option.textContent = item.app;
            select.appendChild(option);
        });

        if (selected) select.value = selected;
    },

    updateLimitsList() {
        const list = nodes.limitsList;
        list.replaceChildren();

        if (state.limits.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = '制限時間が設定されていません';
            list.appendChild(empty);
            return;
        }

        state.limits.forEach((limit) => {
            list.appendChild(this.createLimitRow(limit));
        });
    },

    /** 制限の判定に使う、そのアプリのこのPCでの使用秒数を返す
     *
     * トラッカーはこのPCの使用時間だけで通知を出すため、
     * 画面もスマホ分を含めない値で揃える（含めると通知と食い違う）。
     */
    localSeconds(app) {
        const item = state.todayData.find((row) => row.app === app);
        return item?.device_seconds?.[devices.local] ?? 0;
    },

    /** 制限設定1件分の行を組み立てる */
    createLimitRow(limit) {
        const used = this.localSeconds(limit.app);
        const total = limit.minutes * 60;
        const ratio = total > 0 ? used / total : 0;
        const remaining = total - used;

        const row = document.createElement('div');
        row.className = 'limit-row';
        // 超過と、通知の予告に入った状態だけ色を変える
        if (remaining <= 0) {
            row.classList.add('over');
        } else if (remaining <= LIMIT_NEAR_SECONDS) {
            row.classList.add('near');
        }

        const name = document.createElement('div');
        name.className = 'limit-name';
        name.textContent = limit.app;

        const badge = document.createElement('span');
        badge.className = 'limit-badge';
        badge.textContent = `${format.duration(used)} / ${format.minutes(limit.minutes)}`;
        badge.title = remaining > 0
            ? `残り ${format.duration(remaining)}`
            : `${format.duration(-remaining)} 超過しています`;

        const head = document.createElement('div');
        head.className = 'limit-head';
        head.append(name, badge);

        const fill = document.createElement('div');
        fill.className = 'limit-gauge-fill';
        fill.style.width = `${Math.min(100, Math.round(ratio * 100))}%`;

        const gauge = document.createElement('div');
        gauge.className = 'limit-gauge';
        gauge.appendChild(fill);

        const main = document.createElement('div');
        main.className = 'limit-main';
        main.append(head, gauge);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn-icon';
        deleteBtn.type = 'button';
        deleteBtn.textContent = '✕';
        deleteBtn.title = `${limit.app} の制限を解除`;
        // アプリ名は dataset で受け渡し、HTMLに埋め込まない
        deleteBtn.dataset.action = 'delete-limit';
        deleteBtn.dataset.app = limit.app;

        const info = document.createElement('div');
        info.className = 'limit-info';
        info.appendChild(deleteBtn);

        row.append(main, info);
        return row;
    },

    /** 端末ごとの合計を見出しへ出す（複数の端末に記録がある場合のみ） */
    updateDeviceNote(items) {
        if (!nodes.deviceNote) return;

        const totals = {};
        items.forEach((item) => {
            Object.entries(item.device_seconds ?? {}).forEach(([device, seconds]) => {
                totals[device] = (totals[device] ?? 0) + seconds;
            });
        });

        const entries = Object.entries(totals).sort((a, b) => b[1] - a[1]);
        nodes.deviceNote.textContent = entries.length > 1
            ? entries.map(([d, s]) => `${devices.label(d)} ${format.duration(s)}`).join(' ・ ')
            : '';
    },

    async refreshChart() {
        const data = await api.get(
            `/api/usage/${state.currentPeriod}?date=${encodeURIComponent(state.date)}`
        );
        if (!data) return;

        // 見出しには対象期間を出す（タイムラインや履歴と揃える）
        if (nodes.usageTitle) {
            nodes.usageTitle.textContent = format.period(data.period, data.start, data.end);
        }

        const items = data.apps
            .filter((item) => item.minutes >= CONFIG.CHART_MIN_MINUTES)
            .slice(0, CONFIG.CHART_MAX_ITEMS);

        state.chartLabels = items.map((item) => item.app);
        state.chartDevices = items.map((item) => item.device_seconds ?? {});
        this.updateDeviceNote(data.apps);
        const labels = state.chartLabels.map((name) => format.truncate(name, CONFIG.CHART_LABEL_LENGTH));
        const values = items.map((item) => item.minutes);

        const colors = values.map((_value, index) => utils.barColor(index));

        // 再生成は負荷が高いため、既存のグラフはデータのみ差し替える
        if (state.chart) {
            state.chart.data.labels = labels;
            const dataset = state.chart.data.datasets[0];
            dataset.data = values;
            dataset.backgroundColor = colors;
            state.chart.update();
            return;
        }

        state.chart = new Chart(nodes.usageChart.getContext('2d'), {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderRadius: 3,
                    maxBarThickness: 56,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: COLORS.surface,
                        titleColor: COLORS.text,
                        bodyColor: COLORS.textSub,
                        borderColor: COLORS.border,
                        borderWidth: 1,
                        padding: 10,
                        cornerRadius: 6,
                        displayColors: false,
                        callbacks: {
                            // 省略前の完全なアプリ名を表示する
                            title: (items) => state.chartLabels[items[0].dataIndex] ?? '',
                            // 複数の端末で使っている場合は内訳も添える
                            afterBody: (items) => {
                                const perDevice = state.chartDevices[items[0].dataIndex] ?? {};
                                const entries = Object.entries(perDevice).sort((a, b) => b[1] - a[1]);
                                if (entries.length < 2) return '';
                                return entries.map(
                                    ([d, sec]) => `${devices.label(d)}: ${format.duration(sec)}`
                                );
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        border: { color: COLORS.border },
                        ticks: {
                            maxRotation: 0,
                            minRotation: 0,
                            color: COLORS.textSub,
                            font: { size: 11 },
                        },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: COLORS.grid },
                        border: { display: false },
                        ticks: {
                            color: COLORS.textMuted,
                            font: { size: 11 },
                            callback: (value) => format.minutes(value),
                        },
                    },
                },
            },
        });

        // 読み込み直後は領域の寸法が未確定なことがあるため、描画後に取り直す
        requestAnimationFrame(() => state.chart?.resize());
    },
};

// ── 操作 ──

const actions = {
    async refreshAll() {
        // 稼働状態と端末の表記は statusBar がまとめて扱う
        const date = encodeURIComponent(state.date);
        const [today, limits, summary] = await Promise.all([
            // 制限を設定するアプリの一覧は、選んだ日のものを使う
            api.get(`/api/usage/today?date=${date}`),
            api.get('/api/limits'),
            // 統計欄はグラフと同じ期間で集計する
            api.get(`/api/usage/summary?date=${date}&period=${state.currentPeriod}`),
        ]);

        // 応答が無い場合は前回の値を残す（アプリ本体が停止しているときなど）
        if (today) state.todayData = today;
        if (summary) state.todaySummary = summary;
        if (limits) state.limits = limits;

        ui.updateSummary();
        ui.updateAppSelect();
        ui.updateLimitsList();
    },

    async setLimit(event) {
        event.preventDefault();

        const app = nodes.limitApp.value;
        if (!app || !state.selectedMinutes) {
            showToast('アプリと制限時間を選択してください');
            return;
        }

        const res = await api.post('/api/limits', { app, minutes: state.selectedMinutes });
        if (!res?.ok) {
            showToast('制限の設定に失敗しました');
            return;
        }

        showToast(`${app} の制限を設定しました`);
        nodes.presets.forEach((btn) => btn.classList.remove('active'));
        state.selectedMinutes = null;
        await this.refreshAll();
    },

    async deleteLimit(app) {
        const res = await api.delete(`/api/limits/${encodeURIComponent(app)}`);
        if (!res?.ok) {
            showToast('制限の解除に失敗しました');
            return;
        }

        showToast(`${app} の制限を解除しました`);
        await this.refreshAll();
    },



    async changePeriod(period, button) {
        state.currentPeriod = period;
        nodes.tabs.forEach((tab) => tab.classList.remove('active'));
        button.classList.add('active');
        // 統計欄もグラフと同じ期間に合わせる
        await this.refreshAll();
        await ui.refreshChart();
    },
};

// ── イベント登録 ──

function setupEvents() {
    nodes.limitForm.addEventListener('submit', (event) => actions.setLimit(event));

    nodes.presets.forEach((button) => {
        button.addEventListener('click', () => {
            nodes.presets.forEach((other) => other.classList.remove('active'));
            button.classList.add('active');
            state.selectedMinutes = parseInt(button.dataset.minutes, 10);
        });
    });

    nodes.tabs.forEach((button) => {
        button.addEventListener('click', () => actions.changePeriod(button.dataset.period, button));
    });

    // 画面の高さで表示サイズが変わるため、グラフの大きさも合わせ直す
    window.addEventListener('resize', () => state.chart?.resize());

    // 削除ボタンは行の再描画で作り直されるため、親要素へ委譲する
    nodes.limitsList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-action="delete-limit"]');
        if (button) actions.deleteLimit(button.dataset.app);
    });
}

// ── 初期化 ──

async function init() {
    setupEvents();
    // 端末の表記を先に用意するため、状態の取り込みを待ってから描画する
    statusBar.init();
    await statusBar.refresh();

    // 日付を切り替えたら、集計もグラフも選んだ日で取り直す
    state.date = dateBar.initialDate();
    dateBar.init(async (date) => {
        state.date = date;
        await actions.refreshAll();
        await ui.refreshChart();
    });
    dateBar.set(state.date);

    await actions.refreshAll();
    await ui.refreshChart();

    setInterval(() => actions.refreshAll(), CONFIG.REFRESH_INTERVAL);
    setInterval(() => ui.refreshChart(), CONFIG.CHART_REFRESH_INTERVAL);
}

init();
