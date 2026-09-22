package io.backtrace.bench.app;

import backtraceio.library.BacktraceCredentials;

/**
 * Credentials pointing at the loopback mock. The SDK derives the metrics universe and token from
 * the submission URL and refuses metrics for hosts it does not recognise, so both accessors are
 * overridden (CONVENTIONS section 11). The token is a fixed public placeholder, not a secret.
 */
public final class BenchCredentials extends BacktraceCredentials {
    private final String token;

    public BenchCredentials(String submissionUrl, String token) {
        super(submissionUrl);
        this.token = token;
    }

    @Override
    public String getUniverseName() {
        return "bench";
    }

    @Override
    public String getSubmissionToken() {
        return token;
    }
}
