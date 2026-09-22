# Harness apps: keep the result writer and mock server reachable; strip everything else.
-keep class io.backtrace.bench.app.** { *; }
# mockwebserver pulls junit/hamcrest as compile deps that are never used at runtime.
-dontwarn org.junit.**
-dontwarn org.hamcrest.**
-dontwarn org.bouncycastle.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**
-dontwarn java.lang.management.**
-dontwarn javax.annotation.**
