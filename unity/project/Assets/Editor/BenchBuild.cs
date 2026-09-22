using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace BacktraceBench.Editor
{
    /// <summary>
    /// Player builds for the integrated-size lane (U4). Invoked with
    ///   Unity -batchmode -quit -projectPath unity/project -executeMethod BacktraceBench.Editor.BenchBuild.BuildAndroid
    ///         -btOut Build/android/bench-sdk.apk -btVariant sdk
    /// The plain variant is the same project rendered without the SDK package (Assets/Benchmarks hidden).
    /// </summary>
    public static class BenchBuild
    {
        public static void BuildAndroid()
        {
            var output = Arg("-btOut") ?? "Build/android/bench.apk";
            var variant = Arg("-btVariant") ?? "sdk";
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output)));
            var target = NamedBuildTarget.Android;
            PlayerSettings.SetApplicationIdentifier(target, "io.backtrace.bench.unity." + variant);
            PlayerSettings.SetScriptingBackend(target, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64 | AndroidArchitecture.X86_64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel23;
            EditorUserBuildSettings.buildAppBundle = false;
            EditorUserBuildSettings.development = false;
            var options = new BuildPlayerOptions
            {
                scenes = new[] { "Assets/Scenes/Bench.unity" },
                locationPathName = output,
                target = BuildTarget.Android,
                options = BuildOptions.None,
            };
            var report = BuildPipeline.BuildPlayer(options);
            Report(report, output);
        }

        public static void BuildIOS()
        {
            var output = Arg("-btOut") ?? "Build/ios";
            var variant = Arg("-btVariant") ?? "sdk";
            var target = NamedBuildTarget.iOS;
            PlayerSettings.SetApplicationIdentifier(target, "io.backtrace.bench.unity." + variant);
            PlayerSettings.SetScriptingBackend(target, ScriptingImplementation.IL2CPP);
            PlayerSettings.iOS.targetOSVersionString = "15.0";
            var options = new BuildPlayerOptions
            {
                scenes = new[] { "Assets/Scenes/Bench.unity" },
                locationPathName = output,
                target = BuildTarget.iOS,
                options = BuildOptions.None,
            };
            Report(BuildPipeline.BuildPlayer(options), output);
        }

        private static void Report(BuildReport report, string output)
        {
            var summary = report.summary;
            Debug.Log(string.Format("BenchBuild: result={0} output={1} totalSize={2} time={3}s",
                summary.result, output, summary.totalSize, summary.totalTime.TotalSeconds));
            if (summary.result != BuildResult.Succeeded)
            {
                EditorApplication.Exit(1);
            }
        }

        private static string Arg(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name) return args[i + 1];
            }
            return null;
        }
    }
}
