using System.Collections;
using System.Diagnostics;
using Backtrace.Unity;
using Backtrace.Unity.Model;
using NUnit.Framework;
using Unity.PerformanceTesting;
using UnityEngine;
using UnityEngine.TestTools;

namespace BacktraceBench
{
    /// <summary>
    /// U2: report path with the request-handler stub. Send() spans several frames (two frame yields plus a
    /// coroutine before the handler is invoked), so it is timed wall-to-callback inside a [UnityTest] coroutine.
    ///   U2.send.e2e_ms   Send(report) to the stub being invoked     U2.send.gc_bytes  bytes allocated on the main thread meanwhile
    ///   U2.tojson_ms     BacktraceData.ToJson() for a prepared exception report
    /// </summary>
    public class U2SendBenchmarks
    {
        private const int Warmup = 5;
        private const int Measurements = 20;

        [UnityTest, Performance]
        public IEnumerator U2_Send()
        {
            BenchHarness.QuietLogs(true);
            Application.targetFrameRate = -1;
            QualitySettings.vSyncCount = 0;
            var writer = new BenchResultWriter("U2");
            var e2e = new SampleGroup("U2.send.e2e_ms", SampleUnit.Millisecond);
            var gc = new SampleGroup("U2.send.gc_bytes", SampleUnit.Byte);
            var exception = BenchHarness.SampleException();

            var client = BenchHarness.NewClient(BenchHarness.NewConfiguration(BenchHarness.NewDatabasePath("u2")));
            yield return null;
            BenchHarness.MockRequests = 0;
            var sends = 0;
            for (var i = 0; i < Warmup + Measurements; i++)
            {
                var before = BenchHarness.MockRequests;
                var callback = false;
                BenchHarness.CollectBeforeMeasure();
                var alloc0 = BenchHarness.AllocatedBytes();
                var sw = Stopwatch.StartNew();
                client.Send(new BacktraceReport(exception), (BacktraceResult _) => { callback = true; });
                var frames = 0;
                while (BenchHarness.MockRequests == before && !callback && frames < 1800)
                {
                    frames++;
                    yield return null;
                }
                sw.Stop();
                var bytes = BenchHarness.AllocatedBytes() - alloc0;
                sends++;
                if (frames >= 1800)
                {
                    writer.Error("send " + i + " never reached the request handler");
                    continue;
                }
                if (i >= Warmup)
                {
                    Measure.Custom(e2e, sw.Elapsed.TotalMilliseconds);
                    Measure.Custom(gc, bytes);
                    writer.Sample("U2.send.e2e_ms", sw.Elapsed.TotalMilliseconds);
                    writer.Sample("U2.send.gc_bytes", bytes);
                    writer.Sample("U2.send.frames", frames);
                }
                // Let the coroutine finish its bookkeeping before the next send.
                yield return null;
            }
            writer.Counter("mock_requests", BenchHarness.MockRequests);
            writer.Counter("mock_requests_expected", sends);
            writer.Counter("live_clients_after", BenchHarness.LiveClients());
            writer.Write();
            BenchHarness.Destroy(client);
            Assert.AreEqual(sends, BenchHarness.MockRequests, "every send must reach the request handler exactly once");
        }

        [Test, Performance]
        public void U2_ToJson()
        {
            BenchHarness.QuietLogs(true);
            var writer = new BenchResultWriter("U2json");
            var report = new BacktraceReport(BenchHarness.SampleException());
            var data = new BacktraceData(report, null, -1);
            var group = new SampleGroup("U2.tojson_ms", SampleUnit.Millisecond);
            var sw = new Stopwatch();
            var invocation = 0;
            Measure.Method(() =>
                {
                    sw.Restart();
                    var json = data.ToJson();
                    sw.Stop();
                    if (string.IsNullOrEmpty(json)) writer.Error("ToJson returned empty output");
                })
                .CleanUp(() =>
                {
                    invocation++;
                    if (invocation > Warmup) writer.Sample("U2.tojson_ms", sw.Elapsed.TotalMilliseconds);
                })
                .WarmupCount(Warmup)
                .MeasurementCount(Measurements)
                .IterationsPerMeasurement(1)
                .SampleGroup(group)
                .Run();
            writer.Write();
        }
    }
}
