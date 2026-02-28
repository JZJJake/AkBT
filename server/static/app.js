let chartInstance = null;
let currentPeriod = 'daily'; // Default period
let syncInterval = null;
let defaultZoomBars = 200;

// Sidebar Resize Logic
const sidebar = document.getElementById('sidebar');
const resizer = document.getElementById('resizer');
let isResizing = false;

resizer.addEventListener('mousedown', (e) => {
    isResizing = true;
    document.body.style.cursor = 'col-resize';
});

document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const newWidth = e.clientX;
    if (newWidth > 150 && newWidth < 600) {
        sidebar.style.width = newWidth + 'px';
        if (chartInstance) chartInstance.resize();
    }
});

document.addEventListener('mouseup', () => {
    isResizing = false;
    document.body.style.cursor = 'default';
});

window.globalStockData = null;
let currentCode = "";
let currentName = "";

function switchPeriod(period) {
    if (currentPeriod === period) return;
    currentPeriod = period;

    // Update active button state
    document.querySelectorAll('.p-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`btn-${period}`).classList.add('active');

    // Use cached if available
    if (window.globalStockData && currentCode === document.getElementById('stockCode').value) {
        const periodData = window.globalStockData[currentPeriod];
        renderChart(periodData, currentCode, currentPeriod, null, currentName);

        const periodName = { 'daily': '日线', 'weekly': '周线', 'monthly': '月线' }[currentPeriod];
        document.getElementById('stockInfo').innerText = `${currentName} ${currentCode} - ${periodName} (${periodData.length} bar)`;
    } else {
        loadData();
    }
}

async function loadData() {
    const code = document.getElementById('stockCode').value;
    if (!code) return alert("请输入股票代码");

    document.getElementById('stockInfo').innerText = `加载中: ${code}...`;

    try {
        const resp = await fetch(`/data/${code}`);
        if (!resp.ok) throw new Error("Fetch failed");

        const json = await resp.json();
        if (json.error) {
            document.getElementById('stockInfo').innerText = "加载失败";
            return alert(json.error);
        }

        window.globalStockData = json.data;
        currentCode = json.code;
        currentName = json.name || '';

        const periodData = json.data[currentPeriod];

        if (!periodData || periodData.length === 0) {
            document.getElementById('stockInfo').innerText = "无数据";
            return alert("未获取到数据");
        }

        renderChart(periodData, currentCode, currentPeriod, null, currentName);

        const periodName = { 'daily': '日线', 'weekly': '周线', 'monthly': '月线' }[currentPeriod];
        document.getElementById('stockInfo').innerText = `${currentName} ${currentCode} - ${periodName} (${periodData.length} bar)`;

    } catch (e) {
        console.error(e);
        document.getElementById('stockInfo').innerText = "加载出错";
        alert("加载数据失败: " + e.message);
    }
}

let batchInterval = null;

async function runBacktest() {
    const isFull = document.getElementById('isFullMarket').checked;
    const cash = document.getElementById('initialCash').value;

    if (isFull) {
        runBatchBacktest();
        return;
    }

    const code = document.getElementById('stockCode').value;

    if (!code) return alert("请输入股票代码");

    const resultBox = document.getElementById('backtestResult');
    resultBox.innerHTML = "正在回测...";

    try {
        const resp = await fetch('/backtest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                code: code,
                start_date: null,
                end_date: null,
                initial_cash: parseFloat(cash)
            })
        });

        const json = await resp.json();
        if (json.error) {
            resultBox.innerHTML = "回测失败: " + json.error;
            return;
        }

        // 显示结果
        const equity = json.equity_curve;
        const finalValue = equity[equity.length - 1].value;
        const returnRate = ((finalValue - parseFloat(cash)) / parseFloat(cash) * 100).toFixed(2);

        let html = `<h3>回测结果</h3>`;
        html += `<p>最终权益: ${finalValue.toFixed(2)}</p>`;
        html += `<p>收益率: ${returnRate}%</p>`;
        html += `<p>交易次数: ${json.trades.length}</p>`;
        html += `<h4>最近交易:</h4><ul>`;

        json.trades.slice(-5).forEach(t => {
            html += `<li>${t.date} ${t.action} @ ${t.price} (${t.reason || ''})</li>`;
        });
        html += `</ul>`;

        resultBox.innerHTML = html;

        // Refresh chart with new data (containing buy_signal)
        if (json.bars) {
            // Bars is a JSON string, need to parse
            try {
                const barData = JSON.parse(json.bars);
                // Convert object of objects/arrays to array of objects
                // pandas to_json(orient='index') returns: {"2020-01-01": {Open:10...}, ...}
                // We need array: [{Date: "2020-01-01", Open:10...}, ...]

                const dataArray = Object.keys(barData).map(date => {
                    const item = barData[date];
                    // item.Date might be missing if index was used, but key is date
                    item.Date = date.split('T')[0]; // Ensure pure date string
                    return item;
                });

                // Sort by Date just in case
                dataArray.sort((a, b) => new Date(a.Date) - new Date(b.Date));

                // Render with backtest results
                renderChart(dataArray, code, currentPeriod, json.trades, json.name || '');

            } catch (e) {
                console.error("Error parsing backtest bars:", e);
            }
        }

    } catch (e) {
        console.error(e);
        resultBox.innerHTML = "回测出错: " + e.message;
    }
}

async function syncData() {
    const progressDiv = document.getElementById('syncProgress');
    const bar = document.getElementById('syncBar');
    const text = document.getElementById('syncText');

    progressDiv.style.display = 'block';
    text.innerText = "Starting Sync...";

    try {
        await fetch('/sync_data', { method: 'POST' });

        // Start polling
        if (syncInterval) clearInterval(syncInterval);
        syncInterval = setInterval(async () => {
            const resp = await fetch('/sync_status');
            const status = await resp.json();

            bar.style.width = status.progress + '%';
            text.innerText = `${status.message} (${status.progress}%)`;

            if (status.status === 'completed' || status.status === 'error') {
                clearInterval(syncInterval);
                if (status.status === 'completed') {
                    if (status.message.includes("up to date")) {
                        document.getElementById('syncTime').innerText = status.message;
                        alert(status.message);
                    } else {
                        document.getElementById('syncTime').innerText = "Last Sync: " + new Date().toLocaleString();
                        alert("数据同步完成！");
                    }
                    text.innerText = "Completed";
                } else {
                    alert("同步出错: " + status.message);
                }
                setTimeout(() => { progressDiv.style.display = 'none'; }, 3000);
            }
        }, 1000);

    } catch (e) {
        alert("同步请求失败: " + e.message);
        progressDiv.style.display = 'none';
    }
}

let screenerInterval = null;

async function runScreener() {
    const resultBox = document.getElementById('screenerResult');
    const progressBox = document.getElementById('screenerProgress');
    const scrBar = document.getElementById('scrBar');
    const scrStatus = document.getElementById('scrStatus');
    const scrCount = document.getElementById('scrCount');
    const scrCurrent = document.getElementById('scrCurrent');

    // Clear previous results and show progress
    resultBox.innerHTML = "";
    progressBox.style.display = 'block';
    scrStatus.innerText = "Initiating...";

    try {
        await fetch('/screener', { method: 'POST' });

        // Start polling
        if (screenerInterval) clearInterval(screenerInterval);

        screenerInterval = setInterval(async () => {
            const resp = await fetch('/screener_status');
            const status = await resp.json();

            // Update Progress UI
            scrBar.style.width = status.progress + '%';
            scrStatus.innerText = status.status === 'running' ? 'Scanning...' : status.status;
            scrCount.innerText = `${status.processed}/${status.total}`;
            scrCurrent.innerText = `Checking: ${status.current_stock}`;

            // Live Result Update (Dynamic)
            if (status.results && status.results.length > 0) {
                let html = `<h3>选股结果 (${status.results.length})</h3>`;
                html += `<div style="max-height: 300px; overflow-y: auto;">`;

                // Show found stocks (Latest at top?)
                // Usually append is better but re-render is simpler for small lists
                const reversedResults = [...status.results].reverse();

                reversedResults.forEach(stock => {
                    html += `<div class="stock-list-item" onclick="selectStock('${stock.code}')">`;
                    html += `<strong>${stock.name || ''} ${stock.code}</strong>`;
                    html += `<span>${stock.date}</span>`;
                    html += `<span>¥${stock.price.toFixed(2)}</span>`;
                    html += `</div>`;
                });
                html += `</div>`;
                resultBox.innerHTML = html;
            }

            if (status.status === 'completed' || status.status === 'error') {
                clearInterval(screenerInterval);
                scrCurrent.innerText = status.message;

                if (status.results.length === 0 && status.status === 'completed') {
                     resultBox.innerHTML = `
                        <h3>选股结果 (0)</h3>
                        <p>未发现符合条件的股票。</p>
                        <p style="color: #888; font-size: 0.8em;">
                            提示：如果这是您第一次运行，请先点击上方“全市场数据同步”按钮，
                            下载完整市场数据后再进行选股。
                        </p>
                    `;
                }

                // Hide progress bar after delay (optional, keeping it visible is good feedback)
                // setTimeout(() => { progressBox.style.display = 'none'; }, 5000);
            }

        }, 800); // Poll every 800ms

    } catch (e) {
        console.error(e);
        resultBox.innerHTML = "Start Failed: " + e.message;
        progressBox.style.display = 'none';
    }
}

async function runBatchBacktest() {
    const pBox = document.getElementById('batchProgress');
    const pBar = document.getElementById('batchBar');
    const pText = document.getElementById('batchStatus');
    const resBox = document.getElementById('backtestResult');

    pBox.style.display = 'block';
    resBox.innerHTML = "";
    pText.innerText = "Initiating Batch Task...";

    try {
        await fetch('/batch_backtest', { method: 'POST' });

        if (batchInterval) clearInterval(batchInterval);

        batchInterval = setInterval(async () => {
            const resp = await fetch('/batch_backtest_status');
            const status = await resp.json();

            pBar.style.width = status.progress + '%';
            pText.innerText = `${status.message} (${status.processed}/${status.total})`;

            if (status.status === 'completed') {
                clearInterval(batchInterval);
                renderBatchResult(status.results);
            } else if (status.status === 'error') {
                clearInterval(batchInterval);
                resBox.innerHTML = "Error: " + status.message;
            }

        }, 1000);

    } catch (e) {
        console.error(e);
        pText.innerText = "Error starting batch task.";
    }
}

function renderBatchResult(results) {
    const resBox = document.getElementById('backtestResult');
    const stats = results.stats;
    const equity = results.equity_curve;

    let html = `<h3>全市场回测统计</h3>`;
    html += `<p>测试股票数: ${stats.total_stocks_tested}</p>`;
    html += `<p>平均收益率: ${stats.avg_return}</p>`;
    html += `<p>胜率: ${stats.win_rate}</p>`;
    html += `<p>平均交易次数: ${stats.avg_trades}</p>`;

    resBox.innerHTML = html;

    renderEquityChart(equity);
}

function renderEquityChart(data) {
    if (chartInstance) chartInstance.dispose();
    const container = document.getElementById('chartContainer');
    chartInstance = echarts.init(container);

    const dates = data.map(i => i.date);
    const values = data.map(i => i.value);

    const option = {
        backgroundColor: '#050505',
        title: { text: '全市场策略平均净值曲线', left: 'center', textStyle: { color: '#00f3ff', fontFamily: 'Orbitron' } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: '#00f3ff' } } },
        grid: { top: 50, bottom: 30, left: 50, right: 30 },
        xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#333' } }, axisLabel: { color: '#888' } },
        yAxis: { scale: true, splitLine: { lineStyle: { color: '#222' } }, axisLine: { lineStyle: { color: '#333' } }, axisLabel: { color: '#888' } },
        series: [{
            name: 'Strategy Index',
            type: 'line',
            data: values,
            itemStyle: { color: '#ff00ff' },
            areaStyle: { color: 'rgba(255, 0, 255, 0.1)' },
            symbol: 'none'
        }]
    };
    chartInstance.setOption(option);
}

function selectStock(code) {
    document.getElementById('stockCode').value = code;
    loadData();
}

function toggleSettings() {
    const modal = document.getElementById('settingsModal');
    if (modal.style.display === 'block') {
        modal.style.display = 'none';
    } else {
        document.getElementById('defaultZoom').value = defaultZoomBars;
        modal.style.display = 'block';
    }
}

function saveSettings() {
    const val = parseInt(document.getElementById('defaultZoom').value);
    if (isNaN(val) || val < 0) {
        alert("请输入有效的数字");
        return;
    }
    defaultZoomBars = val;
    toggleSettings();
    // Re-render chart if active
    if (chartInstance) {
        // We can just get current option and update zoom, but easier to reload
        loadData();
    }
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('settingsModal');
    if (event.target == modal) {
        modal.style.display = "none";
    }
}

let ttChart1 = null;
let ttChart2 = null;

function initMiniCharts() {
    if (!ttChart1) ttChart1 = echarts.init(document.getElementById('ttChart1'));
    if (!ttChart2) ttChart2 = echarts.init(document.getElementById('ttChart2'));
}

function updateMiniCharts(hoverDateStr, mainPeriod) {
    if (!window.globalStockData) return;

    const dData = window.globalStockData.daily || [];
    const wData = window.globalStockData.weekly || [];
    const mData = window.globalStockData.monthly || [];

    let chart1Data = [];
    let chart2Data = [];
    let title1 = "";
    let title2 = "";
    let c1Center = -1;
    let c2Center = -1;

    const findIndex = (data, targetDate) => {
        for(let i=0; i<data.length; i++) {
            if(data[i].Date >= targetDate) return i;
        }
        return Math.max(0, data.length - 1);
    };

    const LOOKBACK = 20; // Show 41 bars total

    const sliceData = (data, index) => {
        const start = Math.max(0, index - LOOKBACK);
        const end = Math.min(data.length, index + LOOKBACK + 1);
        return data.slice(start, end);
    };

    if (mainPeriod === 'daily') {
        if(wData.length > 0) {
            const idx = findIndex(wData, hoverDateStr);
            chart1Data = sliceData(wData, idx);
            c1Center = idx - Math.max(0, idx - LOOKBACK);
            title1 = `所在周线及前后${LOOKBACK}周`;
        }
    } else if (mainPeriod === 'weekly') {
        if(dData.length > 0) {
            const idxD = findIndex(dData, hoverDateStr);
            chart1Data = sliceData(dData, idxD);
            c1Center = idxD - Math.max(0, idxD - LOOKBACK);
            title1 = `所在日线及前后${LOOKBACK}日`;
        }
        if(mData.length > 0) {
            const idxM = findIndex(mData, hoverDateStr);
            chart2Data = sliceData(mData, idxM);
            c2Center = idxM - Math.max(0, idxM - LOOKBACK);
            title2 = `所在月线及前后${LOOKBACK}月`;
        }
    } else if (mainPeriod === 'monthly') {
        if(wData.length > 0) {
            const idx = findIndex(wData, hoverDateStr);
            chart1Data = sliceData(wData, idx);
            c1Center = idx - Math.max(0, idx - LOOKBACK);
            title1 = `所在周线及前后${LOOKBACK}周`;
        }
    }

    const renderMini = (instance, data, titleStr, centerIdx) => {
        if (!data || data.length === 0) return;
        const dates = data.map(i => i.Date);
        const kline = data.map(i => [i.Open, i.Close, i.Low, i.High]);

        const macdHist = data.map(i => i.MACD_HIST || 0);
        const macdDif = data.map(i => i.MACD_DIF || 0);
        const macdDea = data.map(i => i.MACD_DEA || 0);

        const kVal = data.map(i => i.K || 0);
        const dVal = data.map(i => i.D || 0);
        const jVal = data.map(i => i.J || 0);

        const series = [
            { type: 'candlestick', data: kline, xAxisIndex: 0, yAxisIndex: 0, itemStyle: { color: '#ff00ff', color0: '#00ff99', borderColor: '#ff00ff', borderColor0: '#00ff99' } },
            { type: 'bar', data: macdHist, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: (p) => p.value > (p.dataIndex>0?macdHist[p.dataIndex-1]:0) ? '#ff00ff' : '#00ff99' } },
            { type: 'line', data: macdDif, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#fff' } },
            { type: 'line', data: macdDea, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { width: 1, color: '#ffeb3b' } },
            { type: 'line', data: kVal, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#fff' } },
            { type: 'line', data: dVal, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#ffeb3b' } },
            { type: 'line', data: jVal, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#e91e63' } }
        ];

        if (centerIdx >= 0) {
            series[0].markLine = {
                symbol: 'none',
                silent: true,
                data: [{ xAxis: centerIdx }],
                lineStyle: { type: 'dashed', color: '#00f3ff', width: 1, opacity: 0.8 }
            };
        }

        instance.setOption({
            backgroundColor: 'transparent',
            animation: false,
            title: { text: titleStr, textStyle: {fontSize:12, color:'#00f3ff'}, top: 0, left: 30 },
            grid: [
                { top: 25, height: '40%', left: 35, right: 10 },
                { top: '68%', height: '15%', left: 35, right: 10 },
                { top: '85%', height: '10%', left: 35, right: 10 }
            ],
            xAxis: [
                { type: 'category', data: dates, gridIndex: 0, show: false },
                { type: 'category', data: dates, gridIndex: 1, show: false },
                { type: 'category', data: dates, gridIndex: 2, show: true, axisLabel: { fontSize: 9, color: '#888', formatter: (val) => val.substring(5) } }
            ],
            yAxis: [
                { scale: true, gridIndex: 0, show: true, axisLabel: { fontSize: 9, color: '#666', formatter: '{value}' }, splitLine: { show: false } },
                { scale: true, gridIndex: 1, show: false },
                { scale: true, gridIndex: 2, show: false }
            ],
            series: series
        });
    };

    document.getElementById('ttChart1').style.display = chart1Data.length ? 'block' : 'none';
    document.getElementById('ttChart2').style.display = chart2Data.length ? 'block' : 'none';

    if (chart1Data.length) renderMini(ttChart1, chart1Data, title1, c1Center);
    if (chart2Data.length) renderMini(ttChart2, chart2Data, title2, c2Center);
}

function renderChart(data, code, period, trades=null, name='') {
    if (chartInstance) {
        chartInstance.dispose();
    }
    const container = document.getElementById('chartContainer');
    chartInstance = echarts.init(container);

    // Process Data
    const dates = data.map(item => item.Date);
    const klineData = data.map(item => [item.Open, item.Close, item.Low, item.High]);
    const volumes = data.map((item, idx) => [idx, item.Volume, item.Open > item.Close ? 1 : -1]);

    const macdDif = data.map(item => item.MACD_DIF || 0);
    const macdDea = data.map(item => item.MACD_DEA || 0);
    const macdHist = data.map(item => item.MACD_HIST || 0);

    const ema20 = data.map(item => item.EMA20 || null);

    const kVal = data.map(item => item.K || 0);
    const dVal = data.map(item => item.D || 0);
    const jVal = data.map(item => item.J || 0);

    // Generate Mark Points for Buy/Sell
    const markPointData = [];
    if (trades && trades.length > 0) {
        trades.forEach(t => {
            const isBuy = t.action === 'buy';
            markPointData.push({
                name: isBuy ? 'Buy' : 'Sell',
                coord: [t.date, t.price],
                value: isBuy ? 'B' : 'S',
                itemStyle: { color: isBuy ? '#ff00ff' : '#00ff99' }, // Neon Pink for Buy, Green for Sell
                symbol: 'arrow',
                symbolRotate: isBuy ? 0 : 180,
                symbolSize: 12,
                symbolOffset: isBuy ? [0, 15] : [0, -15],
                label: {
                    color: '#fff',
                    fontWeight: 'bold',
                    formatter: '{c}'
                }
            });
        });
    } else {
        // Fallback for simple data view
        data.forEach((item, index) => {
            if (item.buy_signal) {
                markPointData.push({
                    name: 'Buy',
                    coord: [item.Date, item.Low * 0.98],
                    value: 'B',
                    itemStyle: { color: '#ff00ff' },
                    symbol: 'arrow',
                    symbolRotate: 0,
                    symbolSize: 10,
                    symbolOffset: [0, 10],
                    label: { color: '#fff', formatter: '{c}' }
                });
            }
        });
    }

    // KDJ J-Turn Arrow Logic
    // Condition: J < 50 AND J(t) > J(t-1) AND J(t-1) <= J(t-2)
    const jArrowData = [];
    for(let i = 2; i < jVal.length; i++) {
        const jCurr = jVal[i];
        const jPrev = jVal[i-1];
        const jPrev2 = jVal[i-2];

        if (jCurr < 50 && jCurr > jPrev && jPrev <= jPrev2) {
            jArrowData.push({
                xAxis: i,
                yAxis: jCurr,
                value: '', // Remove text
                symbol: 'arrow',
                symbolSize: 8,
                symbolRotate: 0,
                symbolOffset: [0, 10], // Offset below
                itemStyle: { color: 'red' }
            });
        }
    }

    const periodName = { 'daily': '日线', 'weekly': '周线', 'monthly': '月线' }[period];

    // Calculate Zoom
    const totalBars = data.length;
    let startPct = 0;
    if (defaultZoomBars > 0 && totalBars > defaultZoomBars) {
        startPct = 100 - (defaultZoomBars / totalBars * 100);
        if (startPct < 0) startPct = 0;
    }

    const option = {
        backgroundColor: '#1e1e1e', // Match CSS
        animation: false,
        title: [
            { text: `${code} ${periodName}`, left: 'center', textStyle: { color: '#e0e0e0', fontSize: 16 } },
            { text: 'MACD(10,25,7)', left: '65px', top: '64%', textStyle: { color: '#aaa', fontSize: 10 } },
            { text: 'KDJ(9,3,3)', left: '65px', top: '82%', textStyle: { color: '#aaa', fontSize: 10 } }
        ],
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross', lineStyle: { color: '#00f3ff', type: 'dashed' } },
            backgroundColor: 'rgba(11,12,21,0.95)',
            borderColor: '#00f3ff',
            borderWidth: 1,
            textStyle: { color: '#e0e0e0', fontSize: 12, fontFamily: 'Roboto' },
            formatter: function (params) {
                // Simplified Tooltip as requested
                let res = `<b>${params[0].name}</b><br/>`;
                params.forEach(param => {
                    if (param.seriesName === 'KLine') {
                        res += `O: ${param.data[1]} C: ${param.data[2]}<br/>L: ${param.data[3]} H: ${param.data[4]}`;
                    }
                });
                return res;
            }
        },
        axisPointer: { link: { xAxisIndex: 'all' } },
        grid: [
            { left: '60px', right: '30px', height: '45%', top: '30px' },   // KLine
            { left: '60px', right: '30px', height: '10%', top: '50%' },  // Vol
            { left: '60px', right: '30px', height: '15%', top: '63%' },  // MACD
            { left: '60px', right: '30px', height: '15%', top: '81%' }   // KDJ
        ],
        xAxis: [
            { type: 'category', data: dates, gridIndex: 0, axisLine: { lineStyle: { color: '#8392A5' } } },
            { type: 'category', data: dates, gridIndex: 1, show: false },
            { type: 'category', data: dates, gridIndex: 2, show: false },
            { type: 'category', data: dates, gridIndex: 3, show: false }
        ],
        yAxis: [
            { scale: true, gridIndex: 0, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLine: { lineStyle: { color: '#8392A5' } }, axisLabel: { color: '#aaa' } },
            { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
            { scale: true, gridIndex: 2, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLabel: { show: false } },
            { scale: true, gridIndex: 3, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLabel: { show: false } }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: startPct, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2, 3], start: startPct, end: 100, bottom: 5, height: 20, borderColor: '#333', fillerColor: 'rgba(100,100,100,0.5)', textStyle: {color: '#aaa'} }
        ],
        series: [
            // KLine
            {
                type: 'candlestick',
                name: 'KLine',
                data: klineData,
                xAxisIndex: 0,
                yAxisIndex: 0,
                itemStyle: {
                    color: '#ff00ff', // Cyberpunk Pink (Fall)
                    color0: '#00ff99', // Cyberpunk Green (Rise)
                    borderColor: '#ff00ff',
                    borderColor0: '#00ff99'
                },
                markPoint: {
                    data: markPointData
                }
            },
            // EMA20
            {
                type: 'line',
                name: 'EMA20',
                data: ema20,
                xAxisIndex: 0,
                yAxisIndex: 0,
                symbol: 'none',
                smooth: true,
                lineStyle: { width: 1, color: '#ffeb3b' }
            },
            // Volume
            {
                type: 'bar',
                name: 'Volume',
                data: volumes.map(v => v[1]),
                xAxisIndex: 1,
                yAxisIndex: 1,
                itemStyle: {
                    color: (params) => {
                        return klineData[params.dataIndex][1] > klineData[params.dataIndex][0] ? '#FD1050' : '#0CF49B';
                    }
                }
            },
            // MACD
            { type: 'line', name: 'DIF', data: macdDif, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1, color: '#fff' } },
            { type: 'line', name: 'DEA', data: macdDea, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1, color: '#ffeb3b' } },
            {
                type: 'bar', name: 'MACD', data: macdHist, xAxisIndex: 2, yAxisIndex: 2,
                itemStyle: {
                    color: (params) => {
                        const index = params.dataIndex;
                        const current = params.value;
                        const prev = index > 0 ? macdHist[index - 1] : 0;

                        // Rule: Current > Previous => Red, Else => Green
                        return current > prev ? '#FD1050' : '#0CF49B';
                    }
                }
            },
            // KDJ
            { type: 'line', name: 'K', data: kVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#fff' } },
            // { type: 'line', name: 'D', data: dVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#ffeb3b' } }, // Hide D
            { type: 'line', name: 'J', data: jVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#e91e63' } }
        ]
    };

    // Add 0-axis MarkLine for MACD (Series index shifted by +1 due to EMA20)
    // 0:KLine, 1:EMA20, 2:Vol, 3:DIF, 4:DEA, 5:MACDBar
    option.series[5].markLine = {
        symbol: 'none',
        silent: true,
        lineStyle: { color: '#666', type: 'dashed' },
        data: [{ yAxis: 0 }]
    };

    // Add 80/30 lines for KDJ (Red/Green)
    // Index mapping: 0:KLine, 1:EMA20, 2:Vol, 3:DIF, 4:DEA, 5:MACDBar, 6:K, 7:J (D is removed)

    option.series[7].markLine = {
         symbol: 'none',
         silent: true,
         data: [
             { yAxis: 80, lineStyle: { color: 'red', type: 'dashed', width: 1 } },
             { yAxis: 30, lineStyle: { color: 'green', type: 'dashed', width: 1 } }
         ]
    };

    option.series[7].markPoint = {
        data: jArrowData
    };

    chartInstance.setOption(option);
    window.onresize = chartInstance.resize;

    // Attach custom tooltip logic
    chartInstance.on('updateAxisPointer', function (event) {
        const xAxisInfo = event.axesInfo[0];
        if (xAxisInfo && xAxisInfo.value != null) {
            const hoveredIndex = xAxisInfo.value;
            const dateStr = dates[hoveredIndex];

            const tt = document.getElementById('multiFrameTooltip');
            tt.style.display = 'block';
            tt.style.top = '60px'; // Position fixed relative to chart container

            // Dodge Mouse
            const zoomOpt = chartInstance.getOption().dataZoom[0];
            const startPct = zoomOpt.start;
            const endPct = zoomOpt.end;
            const startIdx = Math.floor(dates.length * startPct / 100);
            const endIdx = Math.ceil(dates.length * endPct / 100);
            const visibleMid = (startIdx + endIdx) / 2;

            if (hoveredIndex > visibleMid) {
                // Mouse on right half, put tooltip on left
                tt.style.right = 'auto';
                tt.style.left = '80px';
            } else {
                // Mouse on left half, put tooltip on right
                tt.style.left = 'auto';
                tt.style.right = '40px';
            }

            initMiniCharts();
            updateMiniCharts(dateStr, period);
        }
    });

    chartInstance.getZr().on('mouseout', function () {
         document.getElementById('multiFrameTooltip').style.display = 'none';
    });
}
