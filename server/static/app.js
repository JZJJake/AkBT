let chartInstance = null;
let currentData = null; // Store data for resize

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

async function loadData() {
    const code = document.getElementById('stockCode').value;
    if (!code) return alert("请输入股票代码");

    try {
        const resp = await fetch(`/data/${code}`);
        if (!resp.ok) throw new Error("Fetch failed");

        const json = await resp.json();
        if (json.error) return alert(json.error);

        if (!json.data || json.data.length === 0) {
            return alert("未获取到数据");
        }

        if (!json.data[0].Date) {
            return alert("数据格式错误: 缺少 Date 字段");
        }

        currentData = json.data;
        renderChart(json.data, json.code);
    } catch (e) {
        console.error(e);
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

        // Refresh chart if data loaded (to show signals? Not implemented yet but good practice)

    } catch (e) {
        console.error(e);
        resultBox.innerHTML = "回测出错: " + e.message;
    }
}

function renderChart(data, code) {
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

    const kVal = data.map(item => item.K || 0);
    const dVal = data.map(item => item.D || 0);
    const jVal = data.map(item => item.J || 0);

    // Layout Calculation (Percentage)
    // Total 100%
    // KLine: 50%
    // Vol: 15%
    // MACD: 15%
    // KDJ: 15%
    // Gap: 5% distributed

    const option = {
        backgroundColor: '#000',
        animation: false,
        title: { text: code + ' 日线图', left: 'center', textStyle: { color: '#fff' } },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(50,50,50,0.7)',
            borderColor: '#ccc',
            textStyle: { color: '#fff' }
        },
        axisPointer: { link: { xAxisIndex: 'all' } },
        grid: [
            { left: '5%', right: '5%', height: '45%', top: '5%' },   // KLine
            { left: '5%', right: '5%', height: '10%', top: '52%' },  // Vol
            { left: '5%', right: '5%', height: '15%', top: '64%' },  // MACD
            { left: '5%', right: '5%', height: '15%', top: '81%' }   // KDJ
        ],
        xAxis: [
            { type: 'category', data: dates, gridIndex: 0, axisLine: { lineStyle: { color: '#8392A5' } } },
            { type: 'category', data: dates, gridIndex: 1, show: false },
            { type: 'category', data: dates, gridIndex: 2, show: false },
            { type: 'category', data: dates, gridIndex: 3, show: false }
        ],
        yAxis: [
            { scale: true, gridIndex: 0, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLine: { lineStyle: { color: '#8392A5' } } },
            { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
            { scale: true, gridIndex: 2, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLabel: { show: false } },
            { scale: true, gridIndex: 3, splitLine: { show: true, lineStyle: { color: '#333' } }, axisLabel: { show: false } }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 80, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2, 3], start: 80, end: 100, bottom: 5, height: 20, borderColor: '#333', fillerColor: 'rgba(100,100,100,0.5)' }
        ],
        series: [
            // KLine
            {
                type: 'candlestick',
                name: '日线',
                data: klineData,
                xAxisIndex: 0,
                yAxisIndex: 0,
                itemStyle: {
                    color: '#FD1050',
                    color0: '#0CF49B',
                    borderColor: '#FD1050',
                    borderColor0: '#0CF49B'
                }
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
                    color: (params) => params.value > 0 ? '#FD1050' : '#0CF49B'
                }
            },
            // KDJ
            { type: 'line', name: 'K', data: kVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#fff' } },
            { type: 'line', name: 'D', data: dVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#ffeb3b' } },
            { type: 'line', name: 'J', data: jVal, xAxisIndex: 3, yAxisIndex: 3, symbol: 'none', lineStyle: { width: 1, color: '#e91e63' } }
        ]
    };

    // Add 0-axis MarkLine for MACD
    option.series[2].markLine = {
        symbol: 'none',
        silent: true,
        lineStyle: { color: '#666', type: 'dashed' },
        data: [{ yAxis: 0 }]
    };

    // Add 20/50/80 lines for KDJ
    option.series[5].markLine = {
         symbol: 'none',
         silent: true,
         lineStyle: { color: '#333', type: 'dashed' },
         data: [{ yAxis: 20 }, { yAxis: 50 }, { yAxis: 80 }]
    };

    chartInstance.setOption(option);
    window.onresize = chartInstance.resize;
}
