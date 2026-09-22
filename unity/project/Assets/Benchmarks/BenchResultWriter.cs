using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Backtrace.Unity;
using UnityEngine;

namespace BacktraceBench
{
    /// <summary>
    /// Writes bench-result-<test>.json files (schema/bench-result.schema.json) from per-iteration samples the tests
    /// record themselves, so the shared parser has per-iteration values independently of the performance package
    /// results file. Output directory: the -btBenchOut command-line argument, else Application.persistentDataPath.
    /// </summary>
    public sealed class BenchResultWriter
    {
        private readonly string _test;
        private readonly Dictionary<string, List<double>> _samples = new Dictionary<string, List<double>>();
        private readonly Dictionary<string, double> _counters = new Dictionary<string, double>();
        private readonly List<string> _errors = new List<string>();
        private readonly List<string> _stages = new List<string>();

        public BenchResultWriter(string test)
        {
            _test = test;
        }

        public void Sample(string metric, double value)
        {
            List<double> list;
            if (!_samples.TryGetValue(metric, out list))
            {
                list = new List<double>();
                _samples[metric] = list;
            }
            list.Add(value);
        }

        public void Counter(string name, double value)
        {
            _counters[name] = value;
        }

        public void Error(string message)
        {
            _errors.Add(message);
        }

        public static string OutputDirectory()
        {
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-btBenchOut")
                {
                    return args[i + 1];
                }
            }
            return Application.persistentDataPath;
        }

        public string Write(double totalMs = 0.0)
        {
            var dir = OutputDirectory();
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "bench-result-" + _test + ".json");
            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.Append("  \"schemaVersion\": 1,\n");
            sb.Append("  \"sdk\": \"unity\",\n");
            sb.Append("  \"sdkVersion\": ").Append(Quote(BacktraceClient.VERSION)).Append(",\n");
            sb.Append("  \"variant\": ").Append(Quote(Variant())).Append(",\n");
            sb.Append("  \"scenario\": \"default\",\n");
            sb.Append("  \"appId\": ").Append(Quote(Application.productName)).Append(",\n");
            sb.Append("  \"platform\": ").Append(Quote(Application.isEditor ? "unity-editor" : "unity-" + Application.platform.ToString().ToLowerInvariant())).Append(",\n");
            sb.Append("  \"stages\": [],\n");
            sb.Append("  \"totalMs\": ").Append(totalMs.ToString("R", CultureInfo.InvariantCulture)).Append(",\n");
            sb.Append("  \"counters\": {");
            var first = true;
            foreach (var c in _counters)
            {
                sb.Append(first ? "\n" : ",\n").Append("    ").Append(Quote(c.Key)).Append(": ").Append(c.Value.ToString("R", CultureInfo.InvariantCulture));
                first = false;
            }
            sb.Append(first ? "}" : "\n  }").Append(",\n");
            sb.Append("  \"samples\": {");
            first = true;
            foreach (var s in _samples)
            {
                sb.Append(first ? "\n" : ",\n").Append("    ").Append(Quote(s.Key)).Append(": [");
                for (var i = 0; i < s.Value.Count; i++)
                {
                    if (i > 0) sb.Append(", ");
                    sb.Append(s.Value[i].ToString("R", CultureInfo.InvariantCulture));
                }
                sb.Append("]");
                first = false;
            }
            sb.Append(first ? "}" : "\n  }").Append(",\n");
            sb.Append("  \"device\": {\"os\": ").Append(Quote(SystemInfo.operatingSystem)).Append(", \"model\": ").Append(Quote(SystemInfo.deviceModel))
              .Append(", \"cpuCores\": ").Append(SystemInfo.processorCount).Append(", \"unity\": ").Append(Quote(Application.unityVersion)).Append("}");
            if (_errors.Count > 0)
            {
                sb.Append(",\n  \"errors\": [");
                for (var i = 0; i < _errors.Count; i++)
                {
                    if (i > 0) sb.Append(", ");
                    sb.Append(Quote(_errors[i]));
                }
                sb.Append("]");
            }
            sb.Append("\n}\n");
            File.WriteAllText(path, sb.ToString());
            return path;
        }

        private static string Variant()
        {
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-btVariant")
                {
                    return args[i + 1];
                }
            }
            return "sdk";
        }

        private static string Quote(string s)
        {
            if (s == null) return "\"\"";
            var sb = new StringBuilder("\"");
            foreach (var ch in s)
            {
                switch (ch)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (ch < 0x20) sb.Append("\\u").Append(((int)ch).ToString("x4"));
                        else sb.Append(ch);
                        break;
                }
            }
            return sb.Append('"').ToString();
        }
    }
}
