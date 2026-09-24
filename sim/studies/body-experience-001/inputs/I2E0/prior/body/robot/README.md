# Robot description

robot.xml and meshes/ describe this robot relative to its chassis frame.
interface_mapping.json maps public channels and camera names to the description.
The root pose is a reference convention, not the robot's pose in the task scene.
The model contains no task scene, target, initial encoder values or action plan.
Current joint states and enforced command bounds come from the shared robot API.
XML angles are radians; API joint positions use the same joint sign and zero.
Only the low-level API controls the actual robot. This description is data;
you may interpret it using the installed dependencies and code you write.

Camera calibration and precise mounting transforms are not supplied; camera nodes have been removed.
