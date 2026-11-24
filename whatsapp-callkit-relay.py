from pathlib import Path
# Run from LiveContainer repository root. No network access required.
host=Path('LiveContainerSwiftUI/MultitaskSupport/AppSceneViewController.m')
guest=Path('LiveProcess/main.m')
protocol='''
@protocol LCCallRelay
- (void)requestCallTransaction:(NSData *)data reply:(void (^)(NSError *))reply;
@end
'''
hostcode=protocol+'''
#import <dlfcn.h>
@interface LCCallRelayServer : NSObject <NSXPCListenerDelegate, LCCallRelay>
@property(nonatomic,strong) NSXPCListener *listener;
@property(nonatomic,strong) id controller;
@end
@implementation LCCallRelayServer
- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)connection {
    connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:@protocol(LCCallRelay)];
    connection.exportedObject = self;
    [connection resume];
    return YES;
}
- (void)requestCallTransaction:(NSData *)data reply:(void (^)(NSError *))reply {
    dispatch_async(dispatch_get_main_queue(), ^{
        dlopen("/System/Library/Frameworks/CallKit.framework/CallKit", RTLD_NOW);
        Class cls = NSClassFromString(@"CXTransaction");
        Class ctl = NSClassFromString(@"CXCallController");
        NSError *error = nil;
        if (!cls || !ctl || data.length > 65536) {
            reply([NSError errorWithDomain:@"LCCallRelay" code:1 userInfo:nil]); return;
        }
        id transaction = [NSKeyedUnarchiver unarchivedObjectOfClass:cls fromData:data error:&error];
        if (!transaction) { reply(error ?: [NSError errorWithDomain:@"LCCallRelay" code:2 userInfo:nil]); return; }
        if (!self.controller) self.controller = [[ctl alloc] init];
        SEL sel = NSSelectorFromString(@"requestTransaction:completion:");
        if (![self.controller respondsToSelector:sel]) { reply([NSError errorWithDomain:@"LCCallRelay" code:3 userInfo:nil]); return; }
        void (*invoke)(id,SEL,id,id) = (void *)[self.controller methodForSelector:sel];
        invoke(self.controller,sel,transaction,reply);
    });
}
@end
'''
guestcode=protocol+'''
#import <objc/runtime.h>
static NSXPCConnection *lcCallRelayConnection;
static void (*lcOriginalRequest)(id, SEL, id, void (^)(NSError *));
static void lcRelayRequest(id self, SEL cmd, id transaction, void (^completion)(NSError *)) {
    lcOriginalRequest(self, cmd, transaction, ^(NSError *error) {
        if (![error.domain isEqualToString:@"com.apple.CallKit.error.requesttransaction"] || error.code != 1 || !lcCallRelayConnection) {
            if (completion) completion(error); return;
        }
        NSError *archiveError = nil;
        NSData *data = [NSKeyedArchiver archivedDataWithRootObject:transaction requiringSecureCoding:YES error:&archiveError];
        if (!data) { if (completion) completion(archiveError ?: error); return; }
        id<LCCallRelay> proxy = [lcCallRelayConnection remoteObjectProxyWithErrorHandler:^(NSError *relayError) {
            if (completion) dispatch_async(dispatch_get_main_queue(), ^{ completion(relayError); });
        }];
        [proxy requestCallTransaction:data reply:^(NSError *hostError) {
            if (completion) dispatch_async(dispatch_get_main_queue(), ^{ completion(hostError); });
        }];
    });
}
static void lcInstallCallRelay(NSXPCListenerEndpoint *endpoint) {
    if (!endpoint) return;
    dlopen("/System/Library/Frameworks/CallKit.framework/CallKit", RTLD_NOW);
    Method method = class_getInstanceMethod(NSClassFromString(@"CXCallController"), NSSelectorFromString(@"requestTransaction:completion:"));
    if (!method) return;
    lcCallRelayConnection = [[NSXPCConnection alloc] initWithListenerEndpoint:endpoint];
    lcCallRelayConnection.remoteObjectInterface = [NSXPCInterface interfaceWithProtocol:@protocol(LCCallRelay)];
    [lcCallRelayConnection resume];
    lcOriginalRequest = (void *)method_setImplementation(method, (IMP)lcRelayRequest);
}
'''
def replace(s,a,b):
    if s.count(a)!=1: raise RuntimeError('Expected exactly one anchor: '+a)
    return s.replace(a,b,1)
h=host.read_text(); g=guest.read_text()
h=replace(h,'@interface AppSceneViewController()\n',hostcode+'\n@interface AppSceneViewController()\n@property(nonatomic,strong) LCCallRelayServer *callRelay;\n') if h.count('@interface AppSceneViewController()\n')==1 else replace(h,'@interface AppSceneViewController()\n@property int resizeDebounceToken;',hostcode+'\n@interface AppSceneViewController()\n@property(nonatomic,strong) LCCallRelayServer *callRelay;\n@property int resizeDebounceToken;')
h=replace(h,'    item.userInfo = userInfo;', '''    if ([bundleId.lowercaseString containsString:@"whatsapp"]) {
        self.callRelay = [LCCallRelayServer new];
        self.callRelay.listener = [NSXPCListener anonymousListener];
        self.callRelay.listener.delegate = self.callRelay;
        [self.callRelay.listener resume];
        userInfo[@"lcCallRelayEndpoint"] = self.callRelay.listener.endpoint;
    }
    item.userInfo = userInfo;''')
g=replace(g,'@interface LiveProcessHandler',guestcode+'\n@interface LiveProcessHandler')
g=replace(g,'    return LiveContainerMain(argc, argv);','    lcInstallCallRelay(appInfo[@"lcCallRelayEndpoint"]);\n    return LiveContainerMain(argc, argv);')
host.write_text(h); guest.write_text(g)
print('Patched host and guest. Review git diff before building.')

