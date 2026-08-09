document.addEventListener("DOMContentLoaded", function () {

    const data = JSON.parse(
        document.getElementById("beer-style-data").textContent
    );

    const isDark = document.documentElement.classList.contains("dark");

    const textColor = isDark ? "#e5e7eb" : "#374151";
    const mutedColor = isDark ? "#9ca3af" : "#6b7280";
    const gridColor = isDark ? "#374151" : "#e5e7eb";

    const options = {

        chart: {
            type: "bar",
            height: 600,
            toolbar: {
                show: false
            },
            background: "transparent"
        },

        theme: {
            mode: isDark ? "dark" : "light"
        },

        series: [{
            name: "Nombre de bières",
            data: data.map(item => item.nb_bieres)
        }],

        plotOptions: {
            bar: {
                horizontal: true,
                borderRadius: 4,
                barHeight: "70%"
            }
        },

        dataLabels: {
            enabled: true,
            style: {
                colors: [textColor]
            }
        },

        xaxis: {
            categories: data.map(item => item.style),

            labels: {
                style: {
                    colors: mutedColor
                }
            },

            title: {
                text: "Nombre de bières",
                style: {
                    color: textColor
                }
            },

            axisBorder: {
                color: gridColor
            },

            axisTicks: {
                color: gridColor
            }
        },

        yaxis: {
            labels: {
                style: {
                    colors: mutedColor
                }
            },

            title: {
                text: "Style",
                style: {
                    color: textColor
                }
            }
        },

        grid: {
            borderColor: gridColor,
            strokeDashArray: 4
        },

        tooltip: {
            theme: isDark ? "dark" : "light",

            y: {
                formatter: function (value) {
                    return value + " bière" + (value > 1 ? "s" : "");
                }
            }
        },

        legend: {
            labels: {
                colors: textColor
            }
        }
    };


    const chart = new ApexCharts(
        document.querySelector("#beerStyleChart"),
        options
    );

    chart.render();

});