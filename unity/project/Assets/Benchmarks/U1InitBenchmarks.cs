using System.Diagnostics;
using Backtrace.Unity;
using NUnit.Framework;
using Unity.PerformanceTesting;

namespace BacktraceBench
{
    /// <summary>
    /// U1: BacktraceClient.Initialize (which runs Refresh) on a fresh database directory. One live client per
    /// measurement: the client is destroyed with DestroyImmediate in CleanUp because Initialize creates a new
    /// GameObject on every call when DestroyOnLoad is true.
    ///   U1.init.total    wall time of Initialize (ms)      U1.init.gc_bytes  bytes allocated on the calling thread
    /// </summary>
    public class U1InitBenchmarks
    {
        private const int Warmup = 5;
        private const int Measurements = 20;

        [Test, Performance]
        public void U1_Initialize()
        {
            BenchHarness.QuietLogs(true);
            BenchHarness.MockRequests = 0;
            var writer = new BenchResultWriter("U1");
            var time = new SampleGroup("U1.init.total", SampleUnit.Millisecond);
            var gc = new SampleGroup("U1.init.gc_bytes", SampleUnit.Byte);
            var sw = new Stopwatch();
            BacktraceClient client = null;
            string db = null;
            long allocBefore = 0;
            var invocation = 0;

            Measure.Method(() =>
                {
                    allocBefore = BenchHarness.AllocatedBytes();
                    sw.Restart();
                    client = BenchHarness.NewClient(BenchHarness.NewConfiguration(db));
                    sw.Stop();
                })
                .SetUp(() =>
                {
                    BenchHarness.CollectBeforeMeasure();
                    db = BenchHarness.NewDatabasePath("u1");
                    Assert.AreEqual(0, BenchHarness.LiveClients(), "a previous client leaked into this measurement");
                })
                .CleanUp(() =>
                {
                    var bytes = BenchHarness.AllocatedBytes() - allocBefore;
                    invocation++;
                    if (invocation > Warmup)
                    {
                        Measure.Custom(gc, bytes);
                        writer.Sample("U1.init.total", sw.Elapsed.TotalMilliseconds);
                        writer.Sample("U1.init.gc_bytes", bytes);
                    }
                    BenchHarness.Destroy(client);
                    client = null;
                })
                .WarmupCount(Warmup)
                .MeasurementCount(Measurements)
                .IterationsPerMeasurement(1)
                .SampleGroup(time)
                .Run();

            writer.Counter("mock_requests", BenchHarness.MockRequests);
            writer.Counter("live_clients_after", BenchHarness.LiveClients());
            writer.Counter("measurements", Measurements);
            writer.Write();
            Assert.AreEqual(0, BenchHarness.LiveClients());
            Assert.AreEqual(0, BenchHarness.MockRequests, "Initialize must not send anything");
        }
    }
}
