import React, { forwardRef, useImperativeHandle, useRef, useCallback } from 'react';
import { View, StyleSheet } from 'react-native';
import { WebView } from 'react-native-webview';
import RNFS from 'react-native-fs';

function extractHost(raw: string): string | null {
  if (!raw) return null;
  let s = raw.trim();
  s = s.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, ''); // strips http://, https://, rtsp://, rtsp:// with any scheme
  s = s.replace(/^www\./i, '');                       // strips a leading "www." if present
  s = s.split('/')[0];
  s = s.split('?')[0];
  s = s.split(':')[0]; // drop a trailing :port if the user typed one
  return s || null;
}
function buildHtml(host: string) {
  const streamUrl = `http://${host}:81/stream`;
  return `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>html,body{margin:0;padding:0;background:#000;height:100%;overflow:hidden;}
img{width:100%;height:100%;object-fit:contain;display:block;}</style></head><body>
<img id="cam" src="${streamUrl}" />
<canvas id="cv" style="display:none"></canvas>
<script>
function post(o){ window.ReactNativeWebView.postMessage(JSON.stringify(o)); }
function capture(){
  try {
    var img = document.getElementById('cam');
    if (!img || !img.complete || !img.naturalWidth || !img.naturalHeight) {
      post({ type: 'error', message: 'stream frame buffering or unready' });
      return;
    }
    var cv = document.getElementById('cv');
    var w = img.naturalWidth, h = img.naturalHeight;
    cv.width = w; cv.height = h;
    var ctx = cv.getContext('2d');
    if (!ctx) {
      post({ type: 'error', message: 'canvas context unavailable' });
      return;
    }
    ctx.drawImage(img, 0, 0, w, h);
    post({ type: 'frame', dataUrl: cv.toDataURL('image/jpeg', 0.9) });
  } catch (e) { post({ type: 'error', message: String(e && e.message ? e.message : e) }); }
}
document.getElementById('cam').addEventListener('load', function(){ post({type:'ready'}); });
document.getElementById('cam').addEventListener('error', function(){ post({type:'stream_error'}); });
</script></body></html>`;
}

export interface Esp32StreamViewHandle {
  /** Grabs the currently-displayed frame and returns a file:// URI. */
  captureFrameUri(): Promise<string>;
}

interface Props {
  streamUrlOrHost: string;
  onReady?: () => void;
  onError?: (e: Error) => void;
}



export const Esp32StreamView = forwardRef<Esp32StreamViewHandle, Props>(
  ({ streamUrlOrHost, onReady, onError }, ref) => {
    const webRef = useRef<any>(null);
    const pending = useRef<{ resolve: (v: string) => void; reject: (e: Error) => void } | null>(null);
    const host = extractHost(streamUrlOrHost);

    useImperativeHandle(ref, () => ({
      captureFrameUri() {
        return new Promise<string>((resolve, reject) => {
          if (!webRef.current) return reject(new Error('stream view not mounted'));
          pending.current = { resolve, reject };
          webRef.current.injectJavaScript('capture(); true;');
          setTimeout(() => {
            if (pending.current) {
              pending.current.reject(new Error('capture timed out'));
              pending.current = null;
            }
          }, 6000);
        });
      },
    }));

    const handleMessage = useCallback(
      async (event: any) => {
        let msg: any;
        try { msg = JSON.parse(event.nativeEvent.data); } catch { return; }

        if (msg.type === 'frame') {
          if (pending.current) {
            try {
              const base64 = msg.dataUrl.split(',')[1];
              const path = `${RNFS.CachesDirectoryPath}/esp32_frame_${Date.now()}.jpg`;
              await RNFS.writeFile(path, base64, 'base64');
              pending.current.resolve(`file://${path}`);
            } catch (e: any) {
              pending.current.reject(e);
            }
            pending.current = null;
          }
        } else if (msg.type === 'error') {
          if (pending.current) { pending.current.reject(new Error(msg.message)); pending.current = null; }
        } else if (msg.type === 'ready') {
          onReady && onReady();
        } else if (msg.type === 'stream_error') {
          onError && onError(new Error('camera stream failed to load'));
        }
      },
      [onReady, onError],
    );

    if (!host) return null;

    return (
      <View style={styles.container}>
        <WebView
          ref={webRef}
          originWhitelist={['*']}
          source={{ html: buildHtml(host), baseUrl: `http://${host}:81` }}
          onMessage={handleMessage}
          javaScriptEnabled
          domStorageEnabled={false}
          mixedContentMode="always"
          style={styles.webview}
        />
      </View>
    );
  },
);

export async function checkEsp32Reachable(streamUrlOrHost: string): Promise<void> {
  const host = extractHost(streamUrlOrHost);
  if (!host) throw new Error('Could not read an IP/host from that value');
  const res = await fetch(`http://${host}/status`);
  if (!res.ok) throw new Error(`camera not reachable (HTTP ${res.status})`);
}

const styles = StyleSheet.create({
  container: { height: 260, borderRadius: 10, overflow: 'hidden', backgroundColor: '#000' },
  webview: { flex: 1, backgroundColor: '#000' },
});