using Backtrace.Unity;
using Backtrace.Unity.Model;
using NUnit.Framework;
using Unity.PerformanceTesting;

namespace BacktraceBench
{
    /// <summary>
    /// U5: breadcrumb append latency (including the periodic overflow rewrite of the breadcrumb file) and
    /// BacktraceDatabase.Reload() with 0 / 8 / 100 records already on disk.
    /// </summary>
    public class U5DatabaseBenchmarks
    {
        private const int Warmup = 5;
        private const int Measurements = 20;

        [Test, Performance]
        public void U5_BreadcrumbAppend()
        {
            BenchHarness.QuietLogs(true);
            var writer = new BenchResultWriter("U5crumbs");
            var configuration = BenchHarness.NewConfiguration(BenchHarness.NewDatabasePath("u5c"), breadcrumbs: true);
            var client = BenchHarness.NewClient(configuration);
            Assert.IsTrue(client.EnableBreadcrumbsSupport() || client.Breadcrumbs != null, "breadcrumbs could not be enabled");
            var n = 0;
            Measure.Method(() => { client.Breadcrumbs.Info("bench crumb " + (n++)); })
                .WarmupCount(Warmup)
                .MeasurementCount(Measurements)
                .IterationsPerMeasurement(50)
                .SampleGroup(new SampleGroup("U5.breadcrumb.append_us", SampleUnit.Microsecond))
                .Run();
            writer.Counter("breadcrumbs_written", n);
            writer.Write();
            BenchHarness.Destroy(client);
        }

        [Test, Performance]
        [TestCase(0)]
        [TestCase(8)]
        [TestCase(100)]
        public void U5_DatabaseReload(int records)
        {
            BenchHarness.QuietLogs(true);
            var writer = new BenchResultWriter("U5reload" + records);
            var configuration = BenchHarness.NewConfiguration(BenchHarness.NewDatabasePath("u5r" + records));
            configuration.MaxRecordCount = 500;
            var client = BenchHarness.NewClient(configuration);
            var report = new BacktraceReport(BenchHarness.SampleException());
            for (var i = 0; i < records; i++)
            {
                client.Database.Add(new BacktraceData(report, null, -1), false);
            }
            var metric = "U5.db_reload.seeded_" + records;
            Measure.Method(() => { client.Database.Reload(); })
                .WarmupCount(Warmup)
                .MeasurementCount(Measurements)
                .IterationsPerMeasurement(1)
                .SampleGroup(new SampleGroup(metric, SampleUnit.Millisecond))
                .Run();
            writer.Counter("records", records);
            writer.Write();
            client.Database.Clear();
            BenchHarness.Destroy(client);
        }
    }
}
