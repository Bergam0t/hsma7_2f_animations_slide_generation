import simpy
from sim_tools.distributions import Exponential, Lognormal
import pandas as pd
import math
from scipy import stats
import numpy as np
from vidigi.logging import EventLogger, TrialLogger  # UPDATED
from vidigi.utils import create_event_position_df, EventPosition
from vidigi.resources import VidigiStore
from vidigi.process_mapping import (  # NEW
    add_sim_timestamp,  # NEW
    discover_dfg,  # NEW
    dfg_to_graphviz,  # NEW
    dfg_to_cytoscape,  # NEW
)  # NEW
from IPython.display import display  # NEW


class Patient:
    def __init__(self, p_id):
        self.id = p_id

        self.q_time_registration = pd.NA
        self.q_time_nurse = pd.NA
        self.q_time_specialist = pd.NA


class Param:
    def __init__(
        self,
        mean_patient_inter=5,
        mean_registration_time=3,
        sd_registration_time=0.5,
        mean_nurse_consult_time=6,
        sd_nurse_consult_time=1,
        mean_specialist_time=60,
        sd_specialist_time=5,
        num_receptionists=1,
        num_nurses=1,
        num_specialists=1,
        specialist_prob=0.3,
        sim_duration=120,
        num_replications=5,
    ):
        self.mean_patient_inter = mean_patient_inter
        self.mean_registration_time = mean_registration_time
        self.sd_registration_time = sd_registration_time
        self.mean_nurse_consult_time = mean_nurse_consult_time
        self.sd_nurse_consult_time = sd_nurse_consult_time
        self.mean_specialist_time = mean_specialist_time
        self.sd_specialist_time = sd_specialist_time
        self.num_receptionists = num_receptionists
        self.num_nurses = num_nurses
        self.num_specialists = num_specialists
        self.specialist_prob = specialist_prob
        self.sim_duration = sim_duration
        self.num_replications = num_replications


class Model:
    def __init__(self, param, replication_id):
        self.param = param
        self.replication_id = replication_id
        self.env = simpy.Environment()
        self.patient_counter = 0

        self.logger = EventLogger(
            env=self.env,
            run_number=self.replication_id,  # UPDATED
        )

        self.receptionist = VidigiStore(
            self.env,
            num_resources=self.param.num_receptionists,
            logger=self.logger,
            label="receptionist",
        )
        self.nurse = VidigiStore(
            self.env,
            num_resources=self.param.num_nurses,
            logger=self.logger,
            label="nurse",
        )

        self.specialist = VidigiStore(
            self.env,
            num_resources=self.param.num_specialists,
            logger=self.logger,
            label="specialist",
        )

        ss = np.random.SeedSequence(self.replication_id)
        seeds = ss.spawn(5)
        self.patient_inter_dist = Exponential(
            mean=self.param.mean_patient_inter, random_seed=seeds[0]
        )
        self.registration_time_dist = Lognormal(
            mean=self.param.mean_registration_time,
            stdev=self.param.sd_registration_time,
            random_seed=seeds[2],
        )
        self.nurse_consult_time_dist = Lognormal(
            mean=self.param.mean_nurse_consult_time,
            stdev=self.param.sd_nurse_consult_time,
            random_seed=seeds[1],
        )

        self.specialist_branch_prob_rng = np.random.default_rng(seeds[3])

        self.specialist_time_dist = Lognormal(
            mean=self.param.mean_specialist_time,
            stdev=self.param.sd_specialist_time,
            random_seed=seeds[4],
        )

        self.list_of_patients = []
        self.mean_q_time_registration = pd.NA
        self.sd_q_time_registration = pd.NA
        self.perc_90_q_time_registration = pd.NA
        self.mean_q_time_nurse = pd.NA
        self.sd_q_time_nurse = pd.NA
        self.perc_90_q_time_nurse = pd.NA
        self.mean_q_time_specialist = pd.NA
        self.sd_q_time_specialist = pd.NA
        self.perc_90_q_time_specialist = pd.NA

    def generator_patient_arrivals(self):
        while True:
            self.patient_counter += 1
            p = Patient(self.patient_counter)
            self.list_of_patients.append(p)
            self.env.process(self.attend_clinic(p))
            sampled_inter = self.patient_inter_dist.sample()
            yield self.env.timeout(sampled_inter)

    def attend_clinic(self, patient):
        self.logger.log_arrival(entity_id=patient.id)
        start_q_registration = self.env.now
        self.logger.log_queue(entity_id=patient.id, event="receptionist_wait_begins")

        with self.receptionist.request(
            entity_id=patient.id,
            start_event="being_seen_by_receptionist",
            end_event="receptionist_visit_ends",
        ) as req:
            yield req
            end_q_registration = self.env.now
            patient.q_time_registration = end_q_registration - start_q_registration
            sampled_reg_act_time = self.registration_time_dist.sample()
            yield self.env.timeout(sampled_reg_act_time)

        start_q_nurse = self.env.now
        self.logger.log_queue(entity_id=patient.id, event="nurse_wait_begins")

        with self.nurse.request(
            entity_id=patient.id,
            start_event="being_seen_by_nurse",
            end_event="nurse_treatment_ends",
        ) as req:
            yield req
            end_q_nurse = self.env.now
            patient.q_time_nurse = end_q_nurse - start_q_nurse
            sampled_nurse_act_time = self.nurse_consult_time_dist.sample()
            yield self.env.timeout(sampled_nurse_act_time)

        if self.specialist_branch_prob_rng.random() < self.param.specialist_prob:
            start_q_specialist = self.env.now
            self.logger.log_queue(entity_id=patient.id, event="specialist_wait_begins")

            with self.specialist.request(
                entity_id=patient.id,
                start_event="being_seen_by_specialist",
                end_event="specialist_treatment_ends",
            ) as req:
                yield req
                end_q_specialist = self.env.now
                patient.q_time_specialist = end_q_specialist - start_q_specialist
                sampled_specialist_act_time = self.specialist_time_dist.sample()
                yield self.env.timeout(sampled_specialist_act_time)

        self.logger.log_departure(entity_id=patient.id)

    def run_model(self):
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=self.param.sim_duration)

    def convert_entity_list_to_dataframe(self, entity_list):
        entity_dateframe = pd.DataFrame(entity.__dict__ for entity in entity_list)

        return entity_dateframe

    def calculate_run_results(self, entity_dataframe):
        self.mean_q_time_registration = entity_dataframe["q_time_registration"].mean()
        self.sd_q_time_registration = entity_dataframe["q_time_registration"].std()
        self.perc_90_q_time_registration = entity_dataframe[
            "q_time_registration"
        ].quantile(0.9)

        self.mean_q_time_nurse = entity_dataframe["q_time_nurse"].mean()
        self.sd_q_time_nurse = entity_dataframe["q_time_nurse"].std()
        self.perc_90_q_time_nurse = entity_dataframe["q_time_nurse"].quantile(0.9)

        self.mean_q_time_specialist = entity_dataframe["q_time_specialist"].mean()
        self.sd_q_time_specialist = entity_dataframe["q_time_specialist"].std()
        self.perc_90_q_time_specialist = entity_dataframe["q_time_specialist"].quantile(
            0.9
        )


class Trial:
    def __init__(self, param):
        self.param = param
        self.list_of_simulation_replications = []
        self.trial_mean_q_time_registration = pd.NA
        self.trial_sd_q_time_registration = pd.NA
        self.trial_perc_90_q_time_registration = pd.NA
        self.trial_mean_q_time_nurse = pd.NA
        self.trial_sd_q_time_nurse = pd.NA
        self.trial_perc_90_q_time_nurse = pd.NA
        self.trial_mean_q_time_specialist = pd.NA
        self.trial_sd_q_time_specialist = pd.NA
        self.trial_perc_90_q_time_specialist = pd.NA
        self.ci_lower_q_time_registration = pd.NA
        self.ci_upper_q_time_registration = pd.NA
        self.se_q_time_registration = pd.NA
        self.ci_lower_q_time_nurse = pd.NA
        self.ci_upper_q_time_nurse = pd.NA
        self.se_q_time_nurse = pd.NA
        self.ci_lower_q_time_specialist = pd.NA
        self.ci_upper_q_time_specialist = pd.NA
        self.se_q_time_specialist = pd.NA

        self.trial_logger = TrialLogger()  # NEW

    def run_trial(self):
        for replication_id in range(self.param.num_replications):
            model_replication = Model(self.param, replication_id)
            model_replication.run_model()
            patient_df = model_replication.convert_entity_list_to_dataframe(
                model_replication.list_of_patients
            )
            model_replication.calculate_run_results(patient_df)
            self.list_of_simulation_replications.append(model_replication)

            self.trial_logger.add_log(model_replication.logger)  # NEW

    def calculate_trial_results(self):
        self.replication_df = pd.DataFrame(
            replication.__dict__ for replication in self.list_of_simulation_replications
        )

        self.trial_mean_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].mean()
        self.trial_sd_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].std()
        self.trial_perc_90_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].quantile(0.9)

        self.trial_mean_q_time_nurse = self.replication_df["mean_q_time_nurse"].mean()
        self.trial_sd_q_time_nurse = self.replication_df["mean_q_time_nurse"].std()
        self.trial_perc_90_q_time_nurse = self.replication_df[
            "mean_q_time_nurse"
        ].quantile(0.9)

        self.trial_mean_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].mean()
        self.trial_sd_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].std()
        self.trial_perc_90_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].quantile(0.9)

        self.se_q_time_registration = self.trial_sd_q_time_registration / math.sqrt(
            self.param.num_replications
        )
        self.se_q_time_nurse = self.trial_sd_q_time_nurse / math.sqrt(
            self.param.num_replications
        )

        self.se_q_time_specialist = self.trial_sd_q_time_specialist / math.sqrt(
            self.param.num_replications
        )

        t = stats.t.ppf(0.975, df=self.param.num_replications - 1)

        self.ci_lower_q_time_registration = self.trial_mean_q_time_registration - (
            t * self.se_q_time_registration
        )
        self.ci_upper_q_time_registration = self.trial_mean_q_time_registration + (
            t * self.se_q_time_registration
        )

        self.ci_lower_q_time_nurse = self.trial_mean_q_time_nurse - (
            t * self.se_q_time_nurse
        )
        self.ci_upper_q_time_nurse = self.trial_mean_q_time_nurse + (
            t * self.se_q_time_nurse
        )

        self.ci_lower_q_time_specialist = self.trial_mean_q_time_specialist - (
            t * self.se_q_time_specialist
        )
        self.ci_upper_q_time_specialist = self.trial_mean_q_time_specialist + (
            t * self.se_q_time_specialist
        )


if __name__ == "__main__":
    base_case_params = Param()
    base_case_trial = Trial(base_case_params)
    base_case_trial.run_trial()
    base_case_trial.calculate_trial_results()

    print("BASE CASE TRIAL RESULTS")
    print("-----------------------")
    print("Queuing Time for Registration")
    print(f"Mean : {base_case_trial.trial_mean_q_time_registration:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_registration:.2f} minutes")
    print(
        f"90th Perc : {base_case_trial.trial_perc_90_q_time_registration:.2f}",
        "minutes",
    )
    print(f"Standard Error : {base_case_trial.se_q_time_registration:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_registration:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_registration:.2f}) minutes",
    )
    print()

    print("Queuing Time for the Nurse")
    print(f"Mean : {base_case_trial.trial_mean_q_time_nurse:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_nurse:.2f} minutes")
    print(f"90th Perc : {base_case_trial.trial_perc_90_q_time_nurse:.2f} minutes")
    print(f"Standard Error : {base_case_trial.se_q_time_nurse:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_nurse:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_nurse:.2f}) minutes",
    )
    print()

    print("Queuing Time for the Specialist")
    print(f"Mean : {base_case_trial.trial_mean_q_time_specialist:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_specialist:.2f} minutes")
    print(
        f"90th Perc : {base_case_trial.trial_perc_90_q_time_specialist:.2f} ", "minutes"
    )
    print(f"Standard Error : {base_case_trial.se_q_time_specialist:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_specialist:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_specialist:.2f}) minutes",
    )
    print()

    # 1. Modify the code above and here so that animations work with the Trial class
    # and generate a single animation to confirm it works

    # NEW
    # The layout is now just a variable - it no longer needs to live in a class
    layout = create_event_position_df(
        [
            EventPosition(event="arrival", x=0, y=850, label="Entrance"),
            EventPosition(
                event="receptionist_wait_begins",
                x=200,
                y=800,
                label="Waiting for Receptionist",
            ),
            EventPosition(
                event="being_seen_by_receptionist",
                x=200,
                y=700,
                label="Being Seen By Receptionist",
                resource="num_receptionists",
            ),
            EventPosition(
                event="nurse_wait_begins", x=200, y=550, label="Waiting for Nurse"
            ),
            EventPosition(
                event="being_seen_by_nurse",
                x=200,
                y=450,
                label="Being Seen By Nurse",
                resource="num_nurses",
            ),
            EventPosition(
                event="specialist_wait_begins",
                x=75,
                y=300,
                label="Waiting for Specialist",
            ),
            EventPosition(
                event="being_seen_by_specialist",
                x=75,
                y=200,
                label="Being Seen By Specialist",
                resource="num_specialists",
            ),
            EventPosition(event="depart", x=200, y=50, label="Exit"),
        ]
    )

    # UPDATED
    # We now get the event log for one run from the trial_logger
    # Remember that the run numbers count from 0
    print(base_case_trial.trial_logger.get_log_by_run(run=0, as_df=True).head(20))

    # UPDATED
    # ... and animate from the trial_logger too, choosing which run to animate
    fig = base_case_trial.trial_logger.animate_activity_log(
        run_number=0,
        event_position_df=layout,
        every_x_time_units=1,
        scenario=base_case_params,
    )

    fig.show()

    # 2. Generate an animation for each run of the model
    for run in range(base_case_params.num_replications):
        fig = base_case_trial.trial_logger.animate_activity_log(
            run_number=run,
            event_position_df=layout,
            every_x_time_units=1,
            scenario=base_case_params,
        )
        print(f"Run {run}")
        fig.show()

    # 3. Explore the EventLogger and TrialLogger visualisations

    # 4. Generate a process map of this system

    # NEW
    # First, we take our event log and add a timestamp column to it, as it's required
    # so that it can display average durations accurately
    my_event_log_timestamp = add_sim_timestamp(
        base_case_trial.trial_logger.get_log_by_run(run=0, as_df=True),
        time_unit="minutes",
        sim_start="09:00:00",
    )

    # Now we'll discover the pathways in the model
    nodes, edges = discover_dfg(my_event_log_timestamp, case_col="entity_id")

    # A static representation of flow through the process
    graphviz_graph = dfg_to_graphviz(nodes, edges, min_frequency=5)
    display(graphviz_graph)

    # An interactive version
    cytoscape_widget = dfg_to_cytoscape(
        nodes,
        edges,
        min_frequency=5,
        spacing_factor=2,
        width=1400,
    )
    display(cytoscape_widget)

    # Alternatively, the trial logger can do all of the above in a single call
    display(
        base_case_trial.trial_logger.generate_dfg(
            run_number=0, input_time_format="minutes", output_format="graphviz-object"
        )
    )

    display(
        base_case_trial.trial_logger.generate_dfg(
            run_number=0, input_time_format="minutes", output_format="cytoscape-jupyter"
        )
    )
