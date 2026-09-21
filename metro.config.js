// const {getDefaultConfig, mergeConfig} = require('@react-native/metro-config');

// /**
//  * Metro configuration
//  * https://reactnative.dev/docs/metro
//  *
//  * Extended with the face-recognition module's model asset extensions so
//  * `.tflite` / `.onnx` / `.ort` files can be required directly from JS if
//  * ever needed for debug tooling. The primary loading path is still native
//  * assets bundled under android/app/src/main/assets/models (see that
//  * folder's README).
//  *
//  * @type {import('metro-config').MetroConfig}
//  */
// const config = {
//   resolver: {
//     assetExts: ['tflite', 'onnx', 'ort', 'db'],
//   },
// };

// module.exports = mergeConfig(getDefaultConfig(__dirname), config);
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

const defaultConfig = getDefaultConfig(__dirname);

module.exports = mergeConfig(defaultConfig, {
  resolver: {
    assetExts: [
      ...defaultConfig.resolver.assetExts,
      'tflite',
      'onnx',
      'ort',
      'db',
    ],
  },
});