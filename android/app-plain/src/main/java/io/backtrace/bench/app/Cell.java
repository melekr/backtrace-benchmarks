package io.backtrace.bench.app;

import io.backtrace.bench.plain.BuildConfig;

/** Benchmark cell injected at build time (-PbtVersion/-PbtVariant/-PbtScenario/-PbtSource). */
final class Cell {
    static final String SDK_VERSION = BuildConfig.BT_VERSION;
    static final String VARIANT = BuildConfig.BT_VARIANT;
    static final String SCENARIO = BuildConfig.BT_SCENARIO;
    static final String SOURCE = BuildConfig.BT_SOURCE;

    private Cell() {}
}
