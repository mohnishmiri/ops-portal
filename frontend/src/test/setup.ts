import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// @testing-library/react registers afterEach(cleanup) automatically when it
// detects the test framework, but in Vitest's vmThreads pool the auto-detection
// can fail because globals aren't yet injected when the module initialises.
// Explicitly registering here is safe: with vmThreads each test file gets its
// own VM context and its own setup-file execution, so this runs once per file.
afterEach(cleanup);
