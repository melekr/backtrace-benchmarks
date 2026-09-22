using Backtrace.Unity;
using NUnit.Framework;
using Unity.PerformanceTesting;
using UnityEngine;

namespace BacktraceBench
{
    /// <summary>
    /// U3: cost of one Debug.Log while the SDK log capture is installed, with and without breadcrumbs.
    /// Exactly one live client during the measurement; the Unity logger stays enabled because the capture hook
    /// is what is being measured.
    ///   U3.log.per_call_us  U3.log.per_call_breadcrumbs_us  U3.log.gc_bytes (per call, no breadcrumbs)
    /// </summary>
    public class U3LogBenchmarks
    {
        private const int Warmup = 5;
        private const int Measurements = 20;
        private const int LogsPerMeasurement = 50;

        private static void RunLogBenchmark(bool breadcrumbs, string metric, BenchResultWriter writer)
        {
            BenchHarness.MockRequests = 0;
            var configuration = BenchHarness.NewConfiguration(BenchHarness.NewDatabasePath(breadcrumbs ? "u3b" : "u3"), breadcrumbs: breadcrumbs);
            configuration.NumberOfLogs = 100;
            var client = BenchHarness.NewClient(configuration);
            Assert.AreEqual(1, BenchHarness.LiveClients());
            if (breadcrumbs)
            {
                Assert.IsTrue(client.EnableBreadcrumbsSupport() || client.Breadcrumbs != null, "breadcrumbs could not be enabled");
            }
            BenchHarness.QuietLogs(false);
            // Measure the SDK capture hook, not the editor's stack-trace capture for every log line.
            Application.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            var n = 0;
            Measure.Method(() => { Debug.Log("bench log line " + (n++)); })
                .WarmupCount(Warmup)
                .MeasurementCount(Measurements)
                .IterationsPerMeasurement(LogsPerMeasurement)
                .SampleGroup(new SampleGroup(metric, SampleUnit.Microsecond))
                .Run();
            if (!breadcrumbs)
            {
                BenchHarness.CollectBeforeMeasure();
                var alloc0 = BenchHarness.AllocatedBytes();
                for (var i = 0; i < 1000; i++) Debug.Log("bench gc line " + i);
                var perCall = (BenchHarness.AllocatedBytes() - alloc0) / 1000.0;
                Measure.Custom(new SampleGroup("U3.log.gc_bytes", SampleUnit.Byte), perCall);
                writer.Sample("U3.log.gc_bytes", perCall);
            }
            BenchHarness.QuietLogs(true);
            writer.Counter("mock_requests", BenchHarness.MockRequests);
            BenchHarness.Destroy(client);
        }

        [Test, Performance]
        public void U3_DebugLog()
        {
            var writer = new BenchResultWriter("U3");
            RunLogBenchmark(false, "U3.log.per_call_us", writer);
            writer.Write();
        }

        [Test, Performance]
        public void U3_DebugLog_Breadcrumbs()
        {
            var writer = new BenchResultWriter("U3b");
            RunLogBenchmark(true, "U3.log.per_call_breadcrumbs_us", writer);
            writer.Write();
        }
    }
}
