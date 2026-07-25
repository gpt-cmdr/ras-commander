# RASDecomp Evidence Index

The full decompiled working files are retained locally under `rasdecomp/` for
this investigation and are not intended as redistributable library source.
This index records the exact artifacts and hashes used to derive the API
contracts in `FINDINGS.md`.

| Version | Artifact | SHA-256 |
|---|---|---|
| 5.0.7 | `RasMapperLib.CreateLandCoverLayer.decompiled.cs` | `57e31eecd8c5f4c5570fecafdaeba37edcbc96fe74d923c83718a7678ea47ae3` |
| 5.0.7 | `RasMapperLib.LandCover.decompiled.cs` | `6e0d55bb8e58b4a5565988de697b2e5e18d7299d83aa42f388e469fc5eaf19dd` |
| 5.0.7 | `RasMapperLib.LandCoverComputable.decompiled.cs` | `d8af28aeed58275a4de665b40d95a00682acbb7a64f01396f3eb325871d4aff2` |
| 5.0.7 | `RasMapperLib.LandCoverFile.decompiled.cs` | `ca6a55c35599144d8d7b52d38b73f54ed2e0a1b08af40302076df05385abe26f` |
| 5.0.7 | `RasMapperLib.RASGeometry.decompiled.cs` | `dae50fbbf6c53f3ad6c16f652f724ed492600397e544bb9617cc65345a7401f0` |
| 5.0.7 | `RasMapperLib.RASLandCoverManningsN.decompiled.cs` | `9aa3deef3bda4220784a90de62e43b53ae3441538eddc650f175e65259c05655` |
| 6.6 | `RasMapperLib.ComputeWindow.decompiled.cs` | `2b3e40c09607c9fd46e7ac62b0dd9bb74ca99157e13e7213f1d9f52a0657facc` |
| 6.6 | `RasMapperLib.CreateLandCoverLayer.decompiled.cs` | `afb160f6e1f9ab297e97edf149f645b05ff9e452a4e470c1c9a04e24c6386ef9` |
| 6.6 | `RasMapperLib.FinalNValueLayer.decompiled.cs` | `2db110b53a0a34494c692b9862b5d383388799698c39041e50687d4846a62a13` |
| 6.6 | `RasMapperLib.LandCoverComputable.decompiled.cs` | `edb54c1029c6ebac1604e69002f6d5bed029a391879f7decce42f436c6fdb791` |
| 6.6 | `RasMapperLib.LandCoverFile.decompiled.cs` | `d9970b581817a803060a87077f48984f1ba719149027a5af1636bca6048f1481` |
| 6.6 | `RasMapperLib.LandCoverLayer.decompiled.cs` | `b2980146b2bb639bbf96d11404da08d86120ad86b9ae28acc8e610f81aedd41f` |
| 6.6 | `RasMapperLib.LandCoverLayerHelper.decompiled.cs` | `ed18cfb35e49ace7c7c1daa0d109e80f43eadfff162bbe1b8908660e408811ca` |
| 6.6 | `RasMapperLib.RASGeometry.decompiled.cs` | `a377d04aa619bbf9afc9d590f86a383a17d69b628da23c35a0e137588f42900a` |

Key recovered contracts:

- 5.x `LandCoverComputable` byte-ID constructor and
  `LandCoverFile.SetInputToByteMap`.
- 5.x `RASGeometry.LandCover` association.
- 6.x `LandCoverComputable` payload constructor,
  `LandCoverLayerHelper.ManningsN`, `TryLoadLayer`, and `Save`.
- 6.x native classification-table save through the library's public
  `TryAssigningNewParamtersUsingTable` method (the spelling is native).
- 6.x `FinalNValueLayer` and geometry land-cover region behavior.
