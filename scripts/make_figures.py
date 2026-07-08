# -*- coding: utf-8 -*-
"""논문용 그래프 생성.

입력: data/experiment_tidy.csv, data/optimal_points.csv (extract_data.py 출력)
출력: figures/*.png (300 dpi), figures/*.pdf (벡터)

그래프 구성
- 점화시기 스윕: x=점화시기[CAD bTDC], λ별 패널, H2 혼합률 3계열
  (노킹 발생점은 빈 마커로 표시)
- 최적점 비교: x=λ, H2 혼합률 3계열
  최적점 = kp(노킹) 미표기 운전점 중 BTE 최대
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# ---- 스타일 (Origin 스타일: 박스 프레임, 안쪽 눈금, 점선 그리드) -------------
H2_LEVELS = [0, 20, 40]
COLORS = {0: "#000000", 20: "#e60000", 40: "#0000e6"}  # 검정/빨강/파랑
MARKERS = {0: "o", 20: "s", 40: "^"}
LABELS = {0: "NG 100%", 20: "H$_2$ 20%", 40: "H$_2$ 40%"}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.labelsize": 13,
    "axes.labelweight": "bold",
    "axes.titlesize": 12,
    "legend.fontsize": 11,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "axes.linewidth": 1.3,
    "axes.edgecolor": "black",
    "axes.grid": True,
    "grid.color": "#999999",
    "grid.linestyle": "--",
    "grid.linewidth": 0.7,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.top": True,
    "ytick.right": True,
    "xtick.major.size": 5,
    "ytick.major.size": 5,
    "xtick.major.width": 1.2,
    "ytick.major.width": 1.2,
    "legend.frameon": True,
    "legend.edgecolor": "black",
    "legend.framealpha": 1.0,
    "legend.fancybox": False,
    "lines.linewidth": 2.0,
    "lines.markersize": 6.5,
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

LAMBDAS_ALL = [1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 1.9]


def style_ax(ax):
    ax.grid(True, axis="both")
    ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(f"figures/{name}.png")
    fig.savefig(f"figures/{name}.pdf")
    plt.close(fig)
    print(f"  figures/{name}.png / .pdf")


# ---- 점화시기 스윕 그래프 (λ별 패널) ----------------------------------------
def sweep_figure(df, ycol, ylabel, name, legend_loc="best"):
    fig, axes = plt.subplots(2, 4, figsize=(12, 6), sharex=False)
    axes = axes.ravel()

    for i, lam in enumerate(LAMBDAS_ALL):
        ax = axes[i]
        sub_l = df[df["lambda_nom"] == lam]
        for h2 in H2_LEVELS:
            s = sub_l[sub_l["h2_vol_set_pct"] == h2].sort_values("spark_btdc")
            if s.empty:
                continue
            ax.plot(s["spark_btdc"], s[ycol], color=COLORS[h2],
                    marker=MARKERS[h2], markersize=0, zorder=2)
            ok = s[~s["knock_flag"]]
            kn = s[s["knock_flag"]]
            ax.plot(ok["spark_btdc"], ok[ycol], linestyle="none",
                    marker=MARKERS[h2], color=COLORS[h2], zorder=3)
            if not kn.empty:  # 노킹 발생점: 빈 마커
                ax.plot(kn["spark_btdc"], kn[ycol], linestyle="none",
                        marker=MARKERS[h2], markerfacecolor="white",
                        markeredgecolor=COLORS[h2], markeredgewidth=1.2, zorder=3)
        ax.set_title(f"$\\lambda$ = {lam}", fontsize=10)
        style_ax(ax)
        if i >= 3:
            ax.set_xlabel("Spark timing [CAD bTDC]")
        if i % 4 == 0:
            ax.set_ylabel(ylabel)

    # 마지막 패널은 범례 전용
    ax = axes[7]
    ax.axis("off")
    handles = [plt.Line2D([], [], color=COLORS[h], marker=MARKERS[h],
                          label=LABELS[h]) for h in H2_LEVELS]
    handles.append(plt.Line2D([], [], color="#52514e", marker="o", linestyle="none",
                              markerfacecolor="white", markeredgecolor="#52514e",
                              label="Knock observed"))
    ax.legend(handles=handles, loc="center")
    axes[3].set_xlabel("Spark timing [CAD bTDC]")

    fig.tight_layout()
    save(fig, name)


# ---- 최적점 비교 그래프 (x = λ) ---------------------------------------------
def opt_lines(ax, opt, ycol):
    for h2 in H2_LEVELS:
        s = opt[opt["h2_vol_set_pct"] == h2].sort_values("lambda_nom")
        ax.plot(s["lambda_nom"], s[ycol], color=COLORS[h2],
                marker=MARKERS[h2], label=LABELS[h2])
    style_ax(ax)
    ax.set_xticks([1.0, 1.2, 1.4, 1.6, 1.8, 2.0])
    ax.set_xlim(0.95, 2.0)


def opt_single(opt, ycol, ylabel, name, legend=True):
    fig, ax = plt.subplots(figsize=(4.6, 3.8))
    opt_lines(ax, opt, ycol)
    ax.set_xlabel("Excess air ratio, $\\lambda$ [-]")
    ax.set_ylabel(ylabel)
    if legend:
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3,
                  columnspacing=1.0, handlelength=1.6, borderaxespad=0.0)
    fig.tight_layout()
    save(fig, name)


def opt_grid(opt, panels, name, ncols=2, figsize=(9.0, 7.0)):
    nrows = int(np.ceil(len(panels) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize)
    axes = np.atleast_1d(axes).ravel()
    for ax, (ycol, ylabel) in zip(axes, panels):
        opt_lines(ax, opt, ycol)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Excess air ratio, $\\lambda$ [-]")
    for ax in axes[len(panels):]:
        ax.axis("off")
    axes[0].legend()
    fig.tight_layout()
    save(fig, name)


def main():
    df = pd.read_csv("data/experiment_tidy.csv")
    opt = pd.read_csv("data/optimal_points.csv")

    print("점화시기 스윕 그래프:")
    sweep_figure(df, "bte_pct", "BTE [%]", "fig01_sweep_bte")
    sweep_figure(df, "nox_gkwh", "NO$_x$ [g/kWh]", "fig02_sweep_nox")
    sweep_figure(df, "thc_gkwh", "THC [g/kWh]", "fig03_sweep_thc")
    sweep_figure(df, "t_exh_c", "Exhaust gas temp. [$^\\circ$C]", "fig04_sweep_texh")

    print("최적점 비교 그래프:")
    opt_single(opt, "bte_pct", "BTE [%]", "fig05_opt_bte")
    opt_single(opt, "spark_btdc", "Optimal spark timing [CAD bTDC]", "fig06_opt_spark")
    opt_grid(opt, [("nox_gkwh", "NO$_x$ [g/kWh]"),
                   ("thc_gkwh", "THC [g/kWh]"),
                   ("ch4_gkwh", "CH$_4$ [g/kWh]"),
                   ("co_gkwh", "CO [g/kWh]")],
             "fig07_opt_emissions")
    opt_grid(opt, [("map_kpa", "MAP [kPa]"),
                   ("t_exh_c", "Exhaust gas temp. [$^\\circ$C]"),
                   ("vol_eff_pct", "Volumetric efficiency [%]"),
                   ("co2_gkwh", "CO$_2$ [g/kWh]")],
             "fig08_opt_intake_exhaust")

    # BTE-NOx 트레이드오프 (최적점, 계열별 희박 한계점만 λ 직접 표기)
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    lean_offsets = {0: (8, 2), 20: (-14, -14), 40: (6, 6)}
    rich_offsets = {0: (6, 2), 20: (6, -11), 40: (-38, -4)}
    for h2 in H2_LEVELS:
        s = opt[opt["h2_vol_set_pct"] == h2].sort_values("lambda_nom")
        ax.plot(s["nox_gkwh"], s["bte_pct"], color=COLORS[h2],
                marker=MARKERS[h2], label=LABELS[h2])
        lean = s.iloc[-1]  # 가장 희박한 점 (λ 최대)
        ax.annotate(f"$\\lambda$={lean['lambda_nom']}",
                    (lean["nox_gkwh"], lean["bte_pct"]),
                    textcoords="offset points", xytext=lean_offsets[h2],
                    fontsize=8, color="#52514e")
        rich = s.iloc[0]  # λ=1.0
        ax.annotate("$\\lambda$=1.0", (rich["nox_gkwh"], rich["bte_pct"]),
                    textcoords="offset points", xytext=rich_offsets[h2],
                    fontsize=8, color="#52514e")
    style_ax(ax)
    ax.set_xlabel("NO$_x$ [g/kWh]")
    ax.set_ylabel("BTE [%]")
    ax.legend(loc="upper right")
    fig.tight_layout()
    save(fig, "fig09_opt_bte_nox_tradeoff")

    print("완료")


if __name__ == "__main__":
    main()
