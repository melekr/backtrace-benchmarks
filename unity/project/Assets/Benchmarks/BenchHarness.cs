using System;
using System.Collections.Generic;
using System.IO;
using Backtrace.Unity;
using Backtrace.Unity.Model;
using UnityEngine;

namespace BacktraceBench
{
    /// <summary>
    /// Shared setup for the editor PlayMode benchmarks (docs/CONVENTIONS.md section 11).
    /// The server URL points at a loopback host so the SDK never derives a universe and metrics stay off;
    /// every report goes through <see cref="BacktraceClient.RequestHandler"/>, so no socket is ever opened.
    /// </summary>
    public static class BenchHarness
    {
        /// <summary>Fixed public placeholder token (64 hex characters) required by the SDK URL parser; not a secret.</summary>
        public const string Token = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        public const string ServerUrl = "http://127.0.0.1:65535/post?format=json&token=" + Token;
        public const int ReportLimit = 100000;

        public static int MockRequests;

        public static string NewDatabasePath(string label)
        {
            var path = Path.Combine(Application.temporaryCachePath, "bt-bench-" + label + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(path);
            return path;
        }

        public static BacktraceConfiguration NewConfiguration(string databasePath, bool breadcrumbs = false, bool database = true)
        {
            var configuration = ScriptableObject.CreateInstance<BacktraceConfiguration>();
            configuration.ServerUrl = ServerUrl;
            configuration.DestroyOnLoad = true;
            configuration.ReportPerMin = ReportLimit;
            configuration.Sampling = 1;
            configuration.HandleUnhandledExceptions = true;
            configuration.EnableMetricsSupport = false;
            configuration.CaptureNativeCrashes = false;
            configuration.HandleANR = false;
            configuration.GameObjectDepth = -1;
            configuration.GenerateScreenshotOnException = false;
            configuration.PerformanceStatistics = true;
            configuration.Enabled = database;
            configuration.CreateDatabase = database;
            configuration.AutoSendMode = false;
            configuration.DatabasePath = databasePath;
            configuration.MaxRecordCount = 1000;
            configuration.MaxDatabaseSize = 0;
            configuration.EnableBreadcrumbsSupport = breadcrumbs;
            return configuration;
        }

        /// <summary>Creates a client with the request-handler stub installed; counts stub invocations in <see cref="MockRequests"/>.</summary>
        public static BacktraceClient NewClient(BacktraceConfiguration configuration, string gameObjectName = "BacktraceBench")
        {
            var client = BacktraceClient.Initialize(configuration, null, gameObjectName);
            client.RequestHandler = (string url, BacktraceData data) =>
            {
                MockRequests++;
                return new BacktraceResult();
            };
            return client;
        }

        public static void Destroy(BacktraceClient client)
        {
            if (client == null)
            {
                return;
            }
            UnityEngine.Object.DestroyImmediate(client.gameObject);
        }

        public static int LiveClients()
        {
            return UnityEngine.Object.FindObjectsOfType<BacktraceClient>().Length;
        }

        /// <summary>
        /// Managed bytes allocated so far. GC.GetAllocatedBytesForCurrentThread is not implemented by Unity's Mono
        /// (it returns 0), so the Mono heap "used" size is the fallback; callers collect before measuring so the
        /// delta is not disturbed by a collection in the middle of a measurement.
        /// </summary>
        public static long AllocatedBytes()
        {
            var precise = GC.GetAllocatedBytesForCurrentThread();
            if (precise > 0) return precise;
            return UnityEngine.Profiling.Profiler.GetMonoUsedSizeLong();
        }

        public static void CollectBeforeMeasure()
        {
            GC.Collect();
            GC.WaitForPendingFinalizers();
        }

        public static void QuietLogs(bool quiet)
        {
            UnityEngine.Debug.unityLogger.logEnabled = !quiet;
        }

        public static Exception SampleException()
        {
            try
            {
                throw new InvalidOperationException("bench exception");
            }
            catch (Exception e)
            {
                return e;
            }
        }
    }
}
