from pathlib import Path

guest = Path("LiveProcess/main.m")
source = guest.read_text()

diagnostics = r'''
#import <objc/runtime.h>
#import <dlfcn.h>

static void (*originalCallRequest)(
    id, SEL, id, void (^)(NSError *)
);

static void writeCallDiagnostic(NSString *message) {
    NSString *line = [NSString stringWithFormat:
        @"%@ %@\n", [NSDate date], message];
    NSLog(@"[CallDiagnostic] %@", line);

    NSString *path = [NSHomeDirectory()
        stringByAppendingPathComponent:
        @"Documents/CallKitDiagnostic.txt"];

    NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];

    @synchronized ([NSFileHandle class]) {
        NSFileHandle *file =
            [NSFileHandle fileHandleForWritingAtPath:path];

        if (file) {
            [file seekToEndOfFile];
            [file writeData:data];
            [file closeFile];
        } else {
            [data writeToFile:path atomically:YES];
        }
    }
}

static void diagnosticCallRequest(
    id self, SEL cmd, id transaction,
    void (^completion)(NSError *)
) {
    writeCallDiagnostic(@"CallKit transaction requested");

    originalCallRequest(self, cmd, transaction,
        ^(NSError *error) {
            writeCallDiagnostic(
                [NSString stringWithFormat:
                    @"Result: %@ code=%ld",
                    error.domain ?: @"SUCCESS",
                    (long)error.code]);

            if (completion) completion(error);
        });
}

static void installCallDiagnostics(void) {
    dlopen("/System/Library/Frameworks/CallKit.framework/CallKit",
           RTLD_NOW);

    Method method = class_getInstanceMethod(
        NSClassFromString(@"CXCallController"),
        NSSelectorFromString(@"requestTransaction:completion:")
    );

    if (!method) {
        writeCallDiagnostic(@"CallKit method unavailable");
        return;
    }

    originalCallRequest = (void *)method_setImplementation(
        method, (IMP)diagnosticCallRequest);

    writeCallDiagnostic(@"CallKit diagnostics installed");
}
'''

anchor = "@interface LiveProcessHandler"
assert source.count(anchor) == 1
source = source.replace(anchor, diagnostics + "\n" + anchor, 1)

anchor = "    return LiveContainerMain(argc, argv);"
assert source.count(anchor) == 1
source = source.replace(
    anchor,
    "    installCallDiagnostics();\n" + anchor,
    1
)

guest.write_text(source)
print("CallKit diagnostic patch applied.")
