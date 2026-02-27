let chartInstance = null;
let currentPeriod = 'daily'; // Default period
let syncInterval = null;

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

function switchPeriod(period) {
    if (currentPeriod === period) return;
    currentPeriod = period;

    // Update active button state
    document.querySelectorAll('.p-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`btn-${period}`).classList.add('active');

    // Reload data with new period
    loadData();
}

async function loadData() {
    const code = document.getElementById('stockCode').value;
    if (!code) return alert("请输入股票代码");

    // Update Stock Info Title (placeholder)
    document.getElementById('stockInfo').innerText = `加载中: ${code}...`;

    try {
        const resp = await fetch(`/data/${code}?period=${currentPeriod}`);
        if (!resp.ok) throw new Error("Fetch failed");

        const json = await resp.json();
        if (json.error) {
            document.getElementById('stockInfo').innerText = "加载失败";
            return alert(json.error);
        }

        if (!json.data || json.data.length === 0) {
            document.getElementById('stockInfo').innerText = "无数据";
            return alert("未获取到数据");
        }

        if (!json.data[0].Date) {
            return alert("数据格式错误: 缺少 Date 字段");
        }

        renderChart(json.data, json.code, currentPeriod);

        // Update Title
        const periodName = { 'daily': '日线', 'weekly': '周线', 'monthly': '月线' }[currentPeriod];
        document.getElementById('stockInfo').innerText = `${json.code} - ${periodName} (${json.data.length} bar)`;

    } catch (e) {
        console.error(e);
        document.getElementById('stockInfo').innerText = "加载出错";
        alert("加载数据失败: " + e.message);
    }
}

async function runBacktest() {
    const code = document.getElementById('stockCode').value;
    const start = document.getElementById('startDate').value;
    const end = document.getElementById('endDate').value;
    const cash = document.getElementById('initialCash').value;

    if (!code || !start) return alert("请输入完整参数");

    const resultBox = document.getElementById('backtestResult');
    resultBox.innerHTML = "正在回测...";

    try {
        const resp = await fetch('/backtest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                code: code,
                start_date: start,
                end_date: end ? end : null,
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
                renderChart(dataArray, code, currentPeriod);

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
                    alert("数据同步完成！");
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
                    html += `<strong>${stock.code}</strong>`;
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

function selectStock(code) {
    document.getElementById('stockCode').value = code;
    loadData();
}

function renderChart(data, code, period) {
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
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(50,50,50,0.9)',
            borderColor: '#555',
            textStyle: { color: '#fff' }
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
            { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 80, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2, 3], start: 80, end: 100, bottom: 5, height: 20, borderColor: '#333', fillerColor: 'rgba(100,100,100,0.5)', textStyle: {color: '#aaa'} }
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
                    color: '#FD1050',
                    color0: '#0CF49B',
                    borderColor: '#FD1050',
                    borderColor0: '#0CF49B'
                },
                markPoint: {
                    data: (data.map((item, index) => {
                        if (item.buy_signal) {
                            return {
                                name: 'Buy',
                                coord: [index, item.Low * 0.98],
                                value: 'B',
                                itemStyle: { color: '#e91e63' },
                                symbolOffset: [0, 10]
                            };
                        }
                        return null;
                    })).filter(item => item !== null),
                    symbol: 'arrow',
                    symbolRotate: 0, // Point Up
                    symbolSize: 10
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
            { type: 'line', name: 'D', data: dVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#ffeb3b' } },
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
    // Note: series index 6 because we added EMA20 at index 1
    // Index mapping: 0:KLine, 1:EMA20, 2:Vol, 3:DIF, 4:DEA, 5:MACDBar, 6:K, 7:D, 8:J

    // Actually let's count properly:
    // 0: KLine
    // 1: EMA20
    // 2: Volume
    // 3: DIF
    // 4: DEA
    // 5: MACD Hist
    // 6: K
    // 7: D
    // 8: J

    option.series[8].markLine = {
         symbol: 'none',
         silent: true,
         data: [
             { yAxis: 80, lineStyle: { color: 'red', type: 'dashed', width: 1 } },
             { yAxis: 30, lineStyle: { color: 'green', type: 'dashed', width: 1 } }
         ]
    };

    option.series[8].markPoint = {
        data: jArrowData
    };

    chartInstance.setOption(option);
    window.onresize = chartInstance.resize;
}
